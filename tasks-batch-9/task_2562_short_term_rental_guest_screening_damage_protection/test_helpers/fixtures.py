"""Composite setup chains built only from endpoints the contract publishes.

The server is restarted between tests, so nothing here may assume a row survives
from an earlier test. Every helper starts from an empty store, walks the same
creation path a real client would walk, and returns the rows it created so the
test can assert against them. Preconditions use the lenient success reader, so a
fixture never masks the assertion the test itself is making.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import (
    CHECK_IN_CLOCK_UTC,
    PROCESS_START_UTC,
    THREE_NIGHT_COMPLETE_CLOCK_UTC,
    TWO_NIGHT_COMPLETE_CLOCK_UTC,
)
from .test_users import (
    ADJUDICATOR,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    make_guest_headers,
    make_host_headers,
)


class Cast:
    """The rows a scenario needs, plus headers for the two entity-backed roles."""

    def __init__(self, host, guest, jurisdiction_rule, property_row):
        self.host = host
        self.guest = guest
        self.jurisdiction_rule = jurisdiction_rule
        self.property = property_row

    @property
    def host_id(self):
        return self.host["id"]

    @property
    def guest_id(self):
        return self.guest["id"]

    @property
    def jurisdiction_rule_id(self):
        return self.jurisdiction_rule["id"]

    @property
    def property_id(self):
        return self.property["id"] if self.property is not None else None

    @property
    def host_headers(self):
        return make_host_headers(self.host_id)

    @property
    def guest_headers(self):
        return make_guest_headers(self.guest_id)


def set_clock(api, when):
    """Move the logical clock, which every deadline and window comparison reads."""
    return get_success_data(api.set_clock(when, headers=PLATFORM_ADMIN))


def reset_clock(api):
    """Return the clock to the instant the process starts from."""
    return set_clock(api, PROCESS_START_UTC)


def create_jurisdiction_rule(api, **overrides):
    return get_success_data(
        api.create_jurisdiction_rule(
            COMPLIANCE_OFFICER, **factories.jurisdiction_rule_payload(**overrides)
        )
    )


def create_host(api, **overrides):
    return get_success_data(
        api.create_host(PLATFORM_ADMIN, **factories.host_payload(**overrides))
    )


def create_guest(api, **overrides):
    return get_success_data(
        api.create_guest(PLATFORM_ADMIN, **factories.guest_payload(**overrides))
    )


def read_property(api, cast):
    """Re-read the listing so the next booking prices against a live version."""
    cast.property = get_success_data(
        api.get_property(cast.property_id, cast.host_headers)
    )
    return cast.property


def read_guest(api, cast):
    cast.guest = get_success_data(api.get_guest(cast.guest_id, PLATFORM_ADMIN))
    return cast.guest


def read_host(api, cast):
    cast.host = get_success_data(api.get_host(cast.host_id, PLATFORM_ADMIN))
    return cast.host


def _setup_listing(api, payload_builder, guest_name, guest_email, host_name, host_email,
                   activate, clock, rule_overrides, property_overrides):
    set_clock(api, clock)
    rule = create_jurisdiction_rule(api, **rule_overrides)
    host = create_host(api, legal_name=host_name, email=host_email)
    guest = create_guest(api, full_name=guest_name, email=guest_email)
    host_headers = make_host_headers(host["id"])
    property_row = get_success_data(
        api.create_property(
            host_headers,
            **payload_builder(host["id"], rule["id"], **property_overrides)
        )
    )
    if activate:
        property_row = get_success_data(
            api.activate_property(property_row["id"], host_headers)
        )
    return Cast(host, guest, rule, property_row)


def setup_waiver_listing(api, guest_name="Ada Fenwick", guest_email="ada@guest.test",
                         host_name="Bayview Stays LLC", host_email="host1@stays.test",
                         activate=True, clock=PROCESS_START_UTC, rule_overrides=None,
                         **property_overrides):
    """An ACTIVE WAIVER listing with a host, a guest and a bound rule set."""
    return _setup_listing(
        api,
        factories.waiver_property_payload,
        guest_name,
        guest_email,
        host_name,
        host_email,
        activate,
        clock,
        rule_overrides or {},
        property_overrides,
    )


def setup_deposit_listing(api, guest_name="Milo Vance", guest_email="milo@guest.test",
                          host_name="Marina Rentals LLC", host_email="host2@stays.test",
                          activate=True, clock=PROCESS_START_UTC, rule_overrides=None,
                          **property_overrides):
    """An ACTIVE DEPOSIT listing carrying a 50000-cent refundable hold."""
    return _setup_listing(
        api,
        factories.deposit_property_payload,
        guest_name,
        guest_email,
        host_name,
        host_email,
        activate,
        clock,
        rule_overrides or {},
        property_overrides,
    )


def add_guest(api, cast, full_name, email):
    """A second guest on the same listing, for calendar and overlap scenarios."""
    return create_guest(api, full_name=full_name, email=email)


def verify_guest(api, guest_id, gov_ref="gov-doc-1", selfie_ref="selfie-doc-1",
                 expires_on="2030-01-01T00:00:00Z"):
    """Two accepted documents, one of them a government ID, so the guest VERIFIES."""
    guest_headers = make_guest_headers(guest_id)
    gov = get_success_data(
        api.create_identity_document(
            guest_headers,
            **factories.government_id_payload(
                guest_id, document_ref=gov_ref, expires_on=expires_on
            )
        )
    )
    selfie = get_success_data(
        api.create_identity_document(
            guest_headers,
            **factories.selfie_payload(
                guest_id, document_ref=selfie_ref, expires_on=expires_on
            )
        )
    )
    gov = get_success_data(
        api.review_identity_document(gov["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    selfie = get_success_data(
        api.review_identity_document(selfie["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    guest = get_success_data(api.get_guest(guest_id, PLATFORM_ADMIN))
    return guest, gov, selfie


def book_stay(api, cast, guest_id=None, check_in="2026-08-10", check_out="2026-08-13",
              guest_count=2, event_declared=False, expected_property_version=None):
    """Request a stay, re-reading the listing version unless one is supplied."""
    if expected_property_version is None:
        expected_property_version = read_property(api, cast)["version"]
    target_guest = guest_id or cast.guest_id
    return get_success_data(
        api.create_reservation(
            make_guest_headers(target_guest),
            **factories.reservation_payload(
                target_guest,
                cast.property_id,
                expected_property_version,
                check_in=check_in,
                check_out=check_out,
                guest_count=guest_count,
                event_declared=event_declared,
            )
        )
    )


def confirm_stay(api, cast, reservation_id):
    return get_success_data(api.confirm_reservation(reservation_id, cast.host_headers))


def check_in_stay(api, cast, reservation_id, clock=CHECK_IN_CLOCK_UTC):
    """Move the clock to the check-in instant, then start the stay."""
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(api.check_in_reservation(reservation_id, cast.host_headers))


def complete_stay(api, cast, reservation_id, clock=THREE_NIGHT_COMPLETE_CLOCK_UTC):
    """Move the clock past the check-out instant, then close the stay out."""
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(api.complete_reservation(reservation_id, cast.host_headers))


def book_and_confirm(api, cast, **kwargs):
    reservation = book_stay(api, cast, **kwargs)
    return confirm_stay(api, cast, reservation["id"])


def complete_three_night_stay(api, cast, guest_id=None, check_in="2026-08-10",
                              check_out="2026-08-13", guest_count=2,
                              event_declared=False):
    """Book, confirm, check in and complete, leaving the claim window open."""
    reservation = book_stay(
        api,
        cast,
        guest_id=guest_id,
        check_in=check_in,
        check_out=check_out,
        guest_count=guest_count,
        event_declared=event_declared,
    )
    confirm_stay(api, cast, reservation["id"])
    check_in_stay(api, cast, reservation["id"])
    return complete_stay(api, cast, reservation["id"])


def complete_two_night_stay(api, cast, guest_id=None, check_in="2026-08-10",
                            check_out="2026-08-12", guest_count=2,
                            event_declared=False):
    """The two-night variant, completed at 2026-08-12T12:00:00Z."""
    reservation = book_stay(
        api,
        cast,
        guest_id=guest_id,
        check_in=check_in,
        check_out=check_out,
        guest_count=guest_count,
        event_declared=event_declared,
    )
    confirm_stay(api, cast, reservation["id"])
    check_in_stay(api, cast, reservation["id"])
    return complete_stay(
        api, cast, reservation["id"], clock=TWO_NIGHT_COMPLETE_CLOCK_UTC
    )


def register_device(api, cast, approve=True, **overrides):
    """Register a monitoring device and, by default, carry it to APPROVED."""
    device = get_success_data(
        api.create_monitoring_device(
            cast.host_headers,
            **factories.monitoring_device_payload(cast.property_id, **overrides)
        )
    )
    if approve:
        get_success_data(api.submit_device_for_review(device["id"], cast.host_headers))
        device = get_success_data(
            api.review_monitoring_device(
                device["id"], COMPLIANCE_OFFICER, decision="APPROVE"
            )
        )
    return device


def file_incident(api, cast, reservation_id, acknowledge=True, **overrides):
    """File an incident against a stay and, by default, substantiate it."""
    incident = get_success_data(
        api.create_incident(
            cast.host_headers, **factories.incident_payload(reservation_id, **overrides)
        )
    )
    if acknowledge:
        incident = get_success_data(
            api.acknowledge_incident(incident["id"], ADJUDICATOR)
        )
    return incident


def add_coverage_layer(api, source, layer_order, limit_cents, deductible_cents,
                       coverage_pct, scope, property_id=None):
    """Publish one rung of the waterfall; layers are compliance-owned rows."""
    return get_success_data(
        api.create_coverage_layer(
            COMPLIANCE_OFFICER,
            **factories.coverage_layer_payload(
                source,
                layer_order,
                limit_cents,
                deductible_cents,
                coverage_pct,
                scope,
                property_id=property_id,
            )
        )
    )


def open_claim(api, cast, reservation_id, claimed_amount_cents, incident_id=None,
               expected_reservation_version=None):
    """Open a claim against a completed stay, re-reading the stay's version."""
    if expected_reservation_version is None:
        reservation = get_success_data(
            api.get_reservation(reservation_id, cast.host_headers)
        )
        expected_reservation_version = reservation["version"]
    payload = factories.damage_claim_payload(
        reservation_id, claimed_amount_cents, expected_reservation_version
    )
    if incident_id is not None:
        payload["incident_id"] = incident_id
    return get_success_data(api.create_damage_claim(cast.host_headers, **payload))


def add_photo_evidence(api, cast, claim_id, count=2, prefix="photo"):
    """The two photographs every claim needs before it may be reviewed."""
    rows = []
    for index in range(1, count + 1):
        rows.append(
            get_success_data(
                api.create_claim_evidence(
                    cast.host_headers,
                    **factories.photo_evidence_payload(
                        claim_id, "{0}-{1}".format(prefix, index)
                    )
                )
            )
        )
    return rows


def add_receipt_evidence(api, cast, claim_id, amount_cents, file_ref="receipt-1"):
    return get_success_data(
        api.create_claim_evidence(
            cast.host_headers,
            **factories.receipt_evidence_payload(claim_id, file_ref, amount_cents)
        )
    )


def add_police_report_evidence(api, cast, claim_id, file_ref="police-report-1"):
    return get_success_data(
        api.create_claim_evidence(
            cast.host_headers,
            **factories.police_report_evidence_payload(claim_id, file_ref)
        )
    )


def add_required_evidence(api, cast, claim_id, claimed_amount_cents):
    """Whatever the amount demands: two photos, a receipt, and a police report."""
    rows = add_photo_evidence(api, cast, claim_id)
    if claimed_amount_cents >= 50000:
        rows.append(
            add_receipt_evidence(api, cast, claim_id, claimed_amount_cents)
        )
    if claimed_amount_cents >= 250000:
        rows.append(add_police_report_evidence(api, cast, claim_id))
    return rows


def claim_under_review(api, cast, reservation_id, claimed_amount_cents,
                       incident_id=None):
    """Open a claim, satisfy its evidence requirement and submit it for review."""
    claim = open_claim(
        api, cast, reservation_id, claimed_amount_cents, incident_id=incident_id
    )
    add_required_evidence(api, cast, claim["id"], claimed_amount_cents)
    return get_success_data(api.submit_claim_for_review(claim["id"], cast.host_headers))


def approve_claim(api, claim_id, approved_amount_cents,
                  decision_reason_code="DAMAGE_CONFIRMED", headers=ADJUDICATOR):
    return get_success_data(
        api.decide_damage_claim(
            claim_id,
            headers,
            decision="APPROVE",
            decision_reason_code=decision_reason_code,
            approved_amount_cents=approved_amount_cents,
        )
    )


def deny_claim(api, claim_id, decision_reason_code="EVIDENCE_INSUFFICIENT",
               headers=ADJUDICATOR):
    return get_success_data(
        api.decide_damage_claim(
            claim_id, headers, decision="DENY",
            decision_reason_code=decision_reason_code,
        )
    )


def block_guest(api, cast, scope, reason_code, headers=None, property_id=None,
                host_id=None, supersedes_entry_id=None, expected_guest_version=None):
    """Enter a ban, re-reading the guest's version as PRD §2.7 requires."""
    if expected_guest_version is None:
        expected_guest_version = read_guest(api, cast)["version"]
    payload = factories.blocklist_entry_payload(
        cast.guest_id,
        scope,
        reason_code,
        expected_guest_version,
        property_id=property_id,
        host_id=host_id,
        supersedes_entry_id=supersedes_entry_id,
    )
    return get_success_data(
        api.create_blocklist_entry(headers or cast.host_headers, **payload)
    )


def run_sweep(api):
    """Advance the epoch and read back what each of the seven phases moved."""
    return get_success_data(api.run_adjudication_sweep(PLATFORM_ADMIN))
