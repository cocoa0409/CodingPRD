"""Client household endpoints — PrivacyOfficer-only by dignity policy
(PRD §2.10, §3.6)."""

from flask import request

from db import store, base_fields, touch
from errors import (ERR_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_VALIDATION,
                    ERR_INVALID_HOUSEHOLD_STATE, ERR_CONSENT_REQUIRED, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body, paginate
from serialize import household_json, issuance_json
from validate import req_str, opt_bool, req_children_sizes
from . import make_blueprint

bp = make_blueprint("households")

PO = ["PrivacyOfficer"]

# Declared cyclic edges of the eligibility state machine (PRD §3.6).
_EDGES = {
    ("PENDING_REVIEW", "ELIGIBLE"),
    ("PENDING_REVIEW", "INELIGIBLE"),
    ("ELIGIBLE", "INELIGIBLE"),
    ("INELIGIBLE", "ELIGIBLE"),
}
_ELIGIBILITY_VALUES = {"PENDING_REVIEW", "ELIGIBLE", "INELIGIBLE"}


def _get_household_or_404(hid):
    h = store.households.get(hid)
    if h is None:
        raise_err(ERR_NOT_FOUND, "Household not found.")
    return h


@bp.route("/households", methods=["POST"])
def create_household():
    _, role = authenticate()
    require_role(role, PO)
    body = get_body()
    # Uniqueness (category 6) precedes full body validation (category 10).
    code = body.get("household_code")
    if isinstance(code, str) and any(h["household_code"] == code
                                     for h in store.households.values()):
        raise_err(ERR_DUPLICATE_CODE, "household_code is already in use.")
    code = req_str(body, "household_code")
    sizes = req_children_sizes(body, "children_sizes")
    consent = opt_bool(body, "consent_on_file")
    restricted = opt_bool(body, "privacy_restricted")
    h = base_fields()
    h.update({
        "household_code": code,
        "children_sizes": sizes,
        "consent_on_file": bool(consent) if consent is not None else False,
        "privacy_restricted": bool(restricted) if restricted is not None else False,
        "eligibility_status": "PENDING_REVIEW",
        "eligibility_reason": None,
    })
    store.households[h["id"]] = h
    return success_object(household_json(h), status=201)


@bp.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    _, role = authenticate()
    require_role(role, PO)
    return success_object(household_json(_get_household_or_404(hid)))


@bp.route("/households/<hid>", methods=["PATCH"])
def patch_household(hid):
    _, role = authenticate()
    require_role(role, PO)
    h = _get_household_or_404(hid)
    body = get_body()

    # Eligibility state machine (state category) is evaluated before full
    # body validation. The consent gate uses the post-update value when the
    # same request also flips consent_on_file.
    target = body.get("eligibility_status")
    if target is not None and target in _ELIGIBILITY_VALUES:
        if (h["eligibility_status"], target) not in _EDGES:
            raise_err(ERR_INVALID_HOUSEHOLD_STATE,
                      "Eligibility transition %s -> %s is not a declared edge."
                      % (h["eligibility_status"], target))
        if target == "ELIGIBLE":
            consent = body.get("consent_on_file", h["consent_on_file"])
            if consent is not True:
                raise_err(ERR_CONSENT_REQUIRED,
                          "A signed consent is required for ELIGIBLE.")

    sizes = None
    if "children_sizes" in body and body["children_sizes"] is not None:
        sizes = req_children_sizes(body, "children_sizes")
    consent = opt_bool(body, "consent_on_file")
    restricted = opt_bool(body, "privacy_restricted")
    if target is not None and target not in _ELIGIBILITY_VALUES:
        raise_err(ERR_VALIDATION, "eligibility_status must be one of "
                                  "PENDING_REVIEW, ELIGIBLE, INELIGIBLE.")
    reason = body.get("eligibility_reason")
    if reason is not None and not isinstance(reason, str):
        raise_err(ERR_VALIDATION, "eligibility_reason must be a string.")

    if sizes is not None:
        h["children_sizes"] = sizes
    if consent is not None:
        h["consent_on_file"] = consent
    if restricted is not None:
        h["privacy_restricted"] = restricted
    if target is not None:
        h["eligibility_status"] = target
        h["eligibility_reason"] = reason  # stored with the decision
    elif "eligibility_reason" in body:
        h["eligibility_reason"] = reason
    touch(h)
    return success_object(household_json(h))


@bp.route("/households/<hid>/issuances", methods=["GET"])
def household_issuances(hid):
    _, role = authenticate()
    require_role(role, PO)
    _get_household_or_404(hid)
    status = request.args.get("status")
    items = [i for i in store.issuances.values()
             if i["household_id"] == hid
             and (status is None or i["status"] == status)]
    items.sort(key=lambda i: i["created_at"])
    return paginate([issuance_json(i) for i in items])
