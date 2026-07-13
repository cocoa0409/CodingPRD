"""Domain search, registration, WHOIS, settings, renewal, reinstate and DNS."""

from flask import Blueprint, request

import config
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from services import cascades, money, pricing
from services.serializers import dns_record_out, domain_out

bp = Blueprint("domains", __name__)

RENEWABLE_STATES = ("ACTIVE", "EXPIRED", "REDEMPTION")


# --------------------------------------------------------------------- search
@bp.get("/domain-search")
@mw.roles_required("Anonymous", "Registrant")
def domain_search():
    domain_name = request.args.get("domain_name")
    tld = request.args.get("tld")
    if domain_name is None or tld is None:
        raise v.bad("domain_name and tld are required.")
    v.domain_label(domain_name)
    if tld not in config.TLDS:
        raise v.bad("tld must be one of %s." % ", ".join(config.TLDS))

    fqdn = pricing.make_fqdn(domain_name, tld)
    return response.ok(
        {
            "domain_name": domain_name,
            "tld": tld,
            "fqdn": fqdn,
            "available": pricing.is_available(fqdn),
            "is_premium": pricing.is_premium(domain_name),
            "base_year_price_cents": pricing.base_year_price(domain_name, tld),
        }
    )


# --------------------------------------------------------------- registration
@bp.post("/domains")
@mw.roles_required("Registrant")
def register_domain():
    data = v.body()
    account_id = v.req_str(data, "account_id")
    domain_name = v.domain_label(v.req_str(data, "domain_name"))
    tld = v.req_enum(data, "tld", config.TLDS)
    term_years = v.req_int(data, "term_years", minimum=1, maximum=config.MAX_TERM_YEARS)
    registrant_name = v.req_str(data, "registrant_name")
    registrant_email = v.req_str(data, "registrant_email")
    whois_privacy = v.opt_bool(data, "whois_privacy", False)
    auto_renew = v.opt_bool(data, "auto_renew", None)

    account = v.get_account(account_id)
    mw.require_owner(account["id"])
    mw.gate_account_suspended()

    fqdn = pricing.make_fqdn(domain_name, tld)
    if not pricing.is_available(fqdn):
        raise ApiError("ERR_DOMAIN_UNAVAILABLE")

    domain = db.base_record()
    domain.update(
        {
            "account_id": account_id,
            "domain_name": domain_name,
            "tld": tld,
            "fqdn": fqdn,
            "is_premium": pricing.is_premium(domain_name),
            "lifecycle_status": "PENDING_PAYMENT",
            "lock_status": "LOCKED",
            "suspension_reason": None,
            "whois_privacy_enabled": whois_privacy,
            "auto_renew_enabled": (
                account["auto_renew_default"] if auto_renew is None else auto_renew
            ),
            "registrant_name": registrant_name,
            "registrant_email": registrant_email,
            "term_years": term_years,
            "_registered_at": None,
            "_expires_at": None,
            "epp_auth_code": None,
        }
    )
    db.domains[domain["id"]] = domain

    base_price = pricing.base_year_price(domain_name, tld)
    lines = [
        {
            "item_type": "DOMAIN_REGISTRATION",
            "reference_id": domain["id"],
            "description": "Registration of %s for %d year(s)" % (fqdn, term_years),
            "quantity": term_years,
            "unit_price_cents": base_price,
        }
    ]
    if whois_privacy:
        lines.append(
            {
                "item_type": "PRIVACY_FEE",
                "reference_id": domain["id"],
                "description": "WHOIS privacy for %s (%d year(s))" % (fqdn, term_years),
                "quantity": term_years,
                "unit_price_cents": config.PRIVACY_FEE_CENTS_PER_YEAR,
            }
        )
    money.create_invoice(account_id, lines)

    return response.created(domain_out(domain, mw.role(), mw.user_id()))


@bp.get("/domains/<domain_id>")
@mw.roles_required(
    "Anonymous",
    "Registrant",
    "SupportAgent",
    "AbuseAnalyst",
    "BillingAdmin",
    "PlatformAdmin",
)
def read_domain(domain_id):
    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])
    return response.ok(domain_out(domain, mw.role(), mw.user_id()))


@bp.get("/domains")
@mw.roles_required(
    "Registrant", "SupportAgent", "AbuseAnalyst", "BillingAdmin", "PlatformAdmin"
)
def list_domains():
    limit, offset = v.pagination()
    account_id = request.args.get("account_id")
    lifecycle_status = v.query_enum("lifecycle_status", config.DOMAIN_LIFECYCLE)
    lock_status = v.query_enum("lock_status", config.LOCK_STATUSES)

    rows = db.ordered(
        db.domains,
        lambda d: (account_id is None or d["account_id"] == account_id)
        and (lifecycle_status is None or d["lifecycle_status"] == lifecycle_status)
        and (lock_status is None or d["lock_status"] == lock_status),
    )
    rows = mw.scope_to_registrant(rows, lambda d: d["account_id"])
    role, user_id = mw.role(), mw.user_id()
    page, total = v.paginate(rows, limit, offset, lambda d: domain_out(d, role, user_id))
    return response.listing(page, limit, offset, total)


# ------------------------------------------------------------------ settings
@bp.patch("/domains/<domain_id>/settings")
@mw.roles_required("Registrant")
def update_settings(domain_id):
    data = v.body()
    whois_privacy = v.opt_bool(data, "whois_privacy", None)
    auto_renew = v.opt_bool(data, "auto_renew", None)
    locked = v.opt_bool(data, "locked", None)

    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])
    mw.gate_account_suspended()

    if domain["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DOMAIN_STATE")

    now = db.clock_now()
    if locked is False:
        registered_at = domain["_registered_at"]
        if registered_at is None or now < registered_at + db.days(config.TRANSFER_LOCK_DAYS):
            raise ApiError("ERR_TRANSFER_LOCK_PERIOD")

    enabling_privacy = whois_privacy is True and not domain["whois_privacy_enabled"]

    if whois_privacy is not None:
        domain["whois_privacy_enabled"] = whois_privacy
    if auto_renew is not None:
        domain["auto_renew_enabled"] = auto_renew
    if locked is not None:
        domain["lock_status"] = "LOCKED" if locked else "UNLOCKED"
    db.touch(domain)

    if enabling_privacy:
        remaining_years = _remaining_whole_years(domain, now)
        money.create_invoice(
            domain["account_id"],
            [
                {
                    "item_type": "PRIVACY_FEE",
                    "reference_id": domain["id"],
                    "description": "WHOIS privacy for %s (%d year(s))"
                    % (domain["fqdn"], remaining_years),
                    "quantity": remaining_years,
                    "unit_price_cents": config.PRIVACY_FEE_CENTS_PER_YEAR,
                }
            ],
        )

    return response.ok(domain_out(domain, mw.role(), mw.user_id()))


def _remaining_whole_years(domain, now):
    expires_at = domain["_expires_at"]
    if expires_at is None:
        return 0
    remaining_days = int((expires_at - now).total_seconds() // 86400)
    if remaining_days <= 0:
        return 0
    return remaining_days // config.DAYS_PER_YEAR


# ------------------------------------------------------- renewal quote / renew
def _renewal_figures(domain, term_years):
    renewal_subtotal = (
        pricing.base_year_price(domain["domain_name"], domain["tld"]) * term_years
    )
    redemption_fee = (
        config.REDEMPTION_FEE_CENTS
        if domain["lifecycle_status"] == "REDEMPTION"
        else 0
    )
    privacy_fee = (
        config.PRIVACY_FEE_CENTS_PER_YEAR * term_years
        if domain["whois_privacy_enabled"]
        else 0
    )
    return renewal_subtotal, redemption_fee, privacy_fee


@bp.get("/domains/<domain_id>/renewal-quote")
@mw.roles_required("Registrant", "BillingAdmin")
def renewal_quote(domain_id):
    term_years = v.query_int("term_years", None, 1, config.MAX_TERM_YEARS)
    if term_years is None:
        raise v.bad("term_years is required.")

    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])

    if domain["lifecycle_status"] not in RENEWABLE_STATES:
        raise ApiError("ERR_DOMAIN_NOT_RENEWABLE")

    renewal_subtotal, redemption_fee, privacy_fee = _renewal_figures(domain, term_years)
    return response.ok(
        {
            "domain_id": domain["id"],
            "term_years": term_years,
            "variant": "QUOTED",
            "lifecycle_status": domain["lifecycle_status"],
            "renewal_subtotal_cents": renewal_subtotal,
            "redemption_fee_cents": redemption_fee,
            "privacy_fee_cents": privacy_fee,
            "quoted_total_cents": renewal_subtotal + redemption_fee + privacy_fee,
            "quoted_at": db.fmt_dt(db.clock_now()),
        }
    )


@bp.post("/domains/<domain_id>/renew")
@mw.roles_required("Registrant", "BillingAdmin")
def renew_domain(domain_id):
    data = v.body()
    term_years = v.req_int(data, "term_years", minimum=1, maximum=config.MAX_TERM_YEARS)
    expected_version = v.req_int(data, "expected_domain_version", minimum=0)

    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])

    if expected_version != domain["version"]:
        raise ApiError("ERR_STALE_DOMAIN_VERSION")

    mw.gate_account_suspended()

    lifecycle = domain["lifecycle_status"]
    if lifecycle not in RENEWABLE_STATES:
        raise ApiError("ERR_DOMAIN_NOT_RENEWABLE")

    now = db.clock_now()
    if lifecycle == "ACTIVE":
        new_expires_at = domain["_expires_at"] + db.years(term_years)
    else:
        new_expires_at = now + db.years(term_years)

    if new_expires_at - now > db.years(config.MAX_TERM_YEARS):
        raise ApiError("ERR_MAX_TERM_EXCEEDED")

    renewal_subtotal, redemption_fee, privacy_fee = _renewal_figures(domain, term_years)
    base_price = pricing.base_year_price(domain["domain_name"], domain["tld"])

    lines = [
        {
            "item_type": "DOMAIN_RENEWAL",
            "reference_id": domain["id"],
            "description": "Renewal of %s for %d year(s)" % (domain["fqdn"], term_years),
            "quantity": term_years,
            "unit_price_cents": base_price,
        }
    ]
    if redemption_fee:
        lines.append(
            {
                "item_type": "REDEMPTION_FEE",
                "reference_id": domain["id"],
                "description": "Redemption restore fee for %s" % domain["fqdn"],
                "quantity": 1,
                "unit_price_cents": config.REDEMPTION_FEE_CENTS,
            }
        )
    if privacy_fee:
        lines.append(
            {
                "item_type": "PRIVACY_FEE",
                "reference_id": domain["id"],
                "description": "WHOIS privacy for %s (%d year(s))"
                % (domain["fqdn"], term_years),
                "quantity": term_years,
                "unit_price_cents": config.PRIVACY_FEE_CENTS_PER_YEAR,
            }
        )

    revived = lifecycle in ("EXPIRED", "REDEMPTION")
    domain["_expires_at"] = new_expires_at
    domain["lifecycle_status"] = "ACTIVE"
    db.touch(domain)
    if revived:
        cascades.refresh_dns_serving(domain)

    money.create_invoice(domain["account_id"], lines)
    return response.ok(domain_out(domain, mw.role(), mw.user_id()))


@bp.post("/domains/<domain_id>/reinstate")
@mw.roles_required("SupportAgent")
def reinstate_domain(domain_id):
    data = v.body()
    v.req_str(data, "reason")
    domain = v.get_domain(domain_id)

    if domain["lifecycle_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_DOMAIN_STATE")

    account = db.accounts.get(domain["account_id"])
    if account is not None and account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED")

    cascades.reinstate_domain(domain)
    return response.ok(domain_out(domain, mw.role(), mw.user_id()))


# ----------------------------------------------------------------------- DNS
@bp.post("/domains/<domain_id>/dns-records")
@mw.roles_required("Registrant")
def create_dns_record(domain_id):
    data = v.body()
    record_type = v.req_enum(data, "record_type", config.DNS_RECORD_TYPES)
    name = v.req_str(data, "name")
    value = v.req_str(data, "value")
    ttl = v.opt_int(data, "ttl", 3600, minimum=60, maximum=86400)
    priority = v.opt_int(data, "priority", None, minimum=0)
    if record_type == "MX" and priority is None:
        raise v.bad("priority is required when record_type is MX.")
    if record_type != "MX" and priority is not None:
        raise v.bad("priority must be absent unless record_type is MX.")

    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])
    mw.gate_account_suspended()

    if domain["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DOMAIN_STATE")

    record = db.base_record()
    record.update(
        {
            "domain_id": domain["id"],
            "record_type": record_type,
            "name": name,
            "value": value,
            "ttl": ttl,
            "priority": priority,
            "serving_enabled": True,
        }
    )
    db.dns_records[record["id"]] = record
    return response.created(dns_record_out(record))


@bp.get("/domains/<domain_id>/dns-records")
@mw.roles_required("Registrant", "SupportAgent", "PlatformAdmin")
def list_dns_records(domain_id):
    limit, offset = v.pagination()
    record_type = v.query_enum("record_type", config.DNS_RECORD_TYPES)

    domain = v.get_domain(domain_id)
    mw.require_owner(domain["account_id"])

    rows = db.ordered(
        db.dns_records,
        lambda r: r["domain_id"] == domain["id"]
        and (record_type is None or r["record_type"] == record_type),
    )
    page, total = v.paginate(rows, limit, offset, dns_record_out)
    return response.listing(page, limit, offset, total)


@bp.delete("/dns-records/<record_id>")
@mw.roles_required("Registrant")
def delete_dns_record(record_id):
    record = v.get_dns_record(record_id)
    domain = db.domains.get(record["domain_id"])
    mw.require_owner(domain["account_id"] if domain else None)
    mw.gate_account_suspended()

    if domain is None or domain["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DOMAIN_STATE")

    if record["record_type"] == "TXT":
        for add_on in db.add_ons.values():
            if (
                add_on["domain_id"] == domain["id"]
                and add_on["add_on_type"] == "SSL_CERT"
                and add_on["status"] in ("PENDING_VALIDATION", "ACTIVE")
                and add_on["validation_token"] == record["value"]
            ):
                raise ApiError("ERR_DNS_RECORD_IN_USE")

    del db.dns_records[record["id"]]
    return response.no_content()
