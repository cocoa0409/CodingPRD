"""State procurement-law configuration rows (PRD 3.1).  Immutable, unversioned."""

from flask import Blueprint

from db import create_row, db, ordered, serialize
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, require_roles)
from response import created_response, object_response
from routes.common import (PIGGYBACK_DOCTRINE, fetch, list_endpoint)
from services import rule_for_state
from validation import (json_body, read_int, read_reciprocity_codes,
                        read_state_code, read_str)

bp = Blueprint("state_law_rules", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)

FIELDS = (
    "state_code",
    "piggyback_doctrine",
    "min_notice_days",
    "requires_lead_agency_in_state",
    "allows_nonprofit_participation",
    "max_contract_term_months",
    "requires_local_solicitation_waiver",
    "reciprocity_state_codes",
)


@bp.route("/coop/state-law-rules", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def create_rule():
    body = json_body(
        allowed=FIELDS,
        required=("state_code", "piggyback_doctrine", "min_notice_days",
                  "requires_lead_agency_in_state", "allows_nonprofit_participation",
                  "max_contract_term_months", "requires_local_solicitation_waiver"),
    )
    state_code = read_state_code(body, "state_code", required=True)
    doctrine = read_str(body, "piggyback_doctrine", required=True,
                        enum=PIGGYBACK_DOCTRINE)
    min_notice_days = read_int(body, "min_notice_days", required=True,
                              minimum=0, maximum=90)
    requires_lead = _read_flag(body, "requires_lead_agency_in_state")
    allows_nonprofit = _read_flag(body, "allows_nonprofit_participation")
    max_term = read_int(body, "max_contract_term_months", required=True,
                        minimum=12, maximum=120)
    requires_waiver = _read_flag(body, "requires_local_solicitation_waiver")
    reciprocity = read_reciprocity_codes(body, own_code=state_code)

    # ladder 57: global natural-key uniqueness
    if rule_for_state(state_code) is not None:
        fail("ERR_DUPLICATE_STATE_LAW_RULE",
             "a configuration row already exists for state_code %s" % state_code)

    row = create_row(
        db.state_law_rules,
        versioned=False,
        state_code=state_code,
        piggyback_doctrine=doctrine,
        min_notice_days=min_notice_days,
        requires_lead_agency_in_state=requires_lead,
        allows_nonprofit_participation=allows_nonprofit,
        max_contract_term_months=max_term,
        requires_local_solicitation_waiver=requires_waiver,
        reciprocity_state_codes=reciprocity,
    )
    return created_response(serialize(row))


def _read_flag(body, key):
    from validation import read_bool
    return read_bool(body, key, required=True)


@bp.route("/coop/state-law-rules", methods=["GET"])
@require_roles(*READ_ROLES)
def list_rules():
    return list_endpoint(
        lambda: ordered(db.state_law_rules),
        {"state_code": ("state_code", None),
         "piggyback_doctrine": ("piggyback_doctrine", PIGGYBACK_DOCTRINE)},
    )


@bp.route("/coop/state-law-rules/<rule_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_rule(rule_id):
    row = fetch(db.state_law_rules, rule_id, "ERR_STATE_LAW_RULE_NOT_FOUND")
    return object_response(serialize(row))
