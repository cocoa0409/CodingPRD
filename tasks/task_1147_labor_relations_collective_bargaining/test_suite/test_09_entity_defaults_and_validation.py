"""Corner entity tests: creation defaults, system fields, not-found, required
and type-constraint violations."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_agreement,
    assert_union,
    create_agreement_payload,
    create_draft_agreement,
    create_proposal_payload,
    create_union,
    create_union_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]


# ---------------------------------------------------------------------------
# Corner: entities / union_create_defaults_and_system_fields
# ---------------------------------------------------------------------------

def test_union_create_defaults(api):
    """PRD §3.1: "The new union is born in `ACTIVE` status with
    `open_information_request_count` initialized to 0."
    PRD §2.10: "`version` (integer): starts at 1 on creation and increments on
    every mutation, including mutations caused by cascading side effects from
    another entity's transition."

    Design: Corner/entities/union_create_defaults_and_system_fields
    """
    union = get_success_data(
        api.create_union(create_union_payload(name="Union CA", union_code="UCA-1"), ADMIN)
    )
    assert union["status"] == "ACTIVE"
    assert union["open_information_request_count"] == 0
    assert union["version"] == 1
    assert is_valid_uuid(union["id"]), "id must be a server-minted UUID"
    fetched = get_success_data(api.get_union(union["id"], ADMIN))
    assert_union(fetched)


# ---------------------------------------------------------------------------
# Corner: entities / agreement_create_computed_defaults
# ---------------------------------------------------------------------------

def test_agreement_create_computed_defaults(api):
    """PRD §3.1: "The agreement is born `DRAFT` with posture `NEGOTIATING`,
    `envelope_committed_cents` at 0, and `extension_count` at 0." and "The
    optional `deadline_mode` selects whether linked information requests use
    `BUSINESS` or `CALENDAR` deadline arithmetic and defaults to `BUSINESS`."

    Design: Corner/entities/agreement_create_computed_defaults
    """
    union = create_union(name="Union CB")
    payload = create_agreement_payload(union_id=union["id"], title="CBA CB")
    payload.pop("deadline_mode", None)  # omit to observe the server default
    agreement = get_success_data(api.create_agreement(payload, ADMIN))
    assert agreement["status"] == "DRAFT"
    assert agreement["posture"] == "NEGOTIATING"
    assert agreement["envelope_committed_cents"] == 0
    assert agreement["extension_count"] == 0
    assert agreement["deadline_mode"] == "BUSINESS"
    assert_agreement(agreement)


# ---------------------------------------------------------------------------
# Corner: entities / proposal_create_round_number_input_ignored
# ---------------------------------------------------------------------------

def test_proposal_create_ignores_client_round_number(api):
    """PRD §3.3: "A new proposal is born `DRAFT` with `round_number` 1 and
    `submitted_by_user_id` recorded from `X-User-ID`."

    Design: Corner/entities/proposal_create_round_number_input_ignored
    """
    union = create_union(name="Union CC")
    agreement = create_draft_agreement(union["id"], title="CBA CC")
    payload = create_proposal_payload(
        agreement_id=agreement["id"],
        side="EMPLOYER",
        title="Draft",
        proposal_type="NON_ECONOMIC",
    )
    payload["round_number"] = 99  # client-supplied system field
    proposal = get_success_data(api.create_proposal(payload, NEG1))
    assert proposal["round_number"] == 1, "client-supplied round_number must be ignored"
    assert proposal["submitted_by_user_id"] == "neg-1"
    assert proposal["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: entities / get_missing_agreement_returns_404
# ---------------------------------------------------------------------------

def test_get_missing_agreement_returns_404(api):
    """PRD §2.11: "the server resolves references in a left-to-right order —
    union, then agreement, then clause, then session, then proposal, then
    scenario, then vote, then letter, then practice, then request, then task —
    and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve."

    Design: Corner/entities/get_missing_agreement_returns_404
    """
    resp = api.get_agreement(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: entities / proposal_missing_required_returns_400
# ---------------------------------------------------------------------------

def test_proposal_missing_title_returns_400(api):
    """PRD §2.11: "Request shape comes next — missing required fields, invalid
    enum members, numeric range violations (`ERR_INVALID_REQUEST`, with
    `ERR_PAGINATION_INVALID` covering list-endpoint limit and offset
    violations)."

    Design: Corner/entities/proposal_missing_required_returns_400
    """
    union = create_union(name="Union CD")
    agreement = create_draft_agreement(union["id"], title="CBA CD")
    payload = {
        "agreement_id": agreement["id"],
        "side": "EMPLOYER",
        "proposal_type": "NON_ECONOMIC",
    }
    resp = api.create_proposal(payload, NEG1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner: entities / proposal_side_invalid_enum_returns_400
# ---------------------------------------------------------------------------

def test_proposal_side_invalid_enum_returns_400(api):
    """PRD §2.11: "Request shape comes next — missing required fields, invalid
    enum members, numeric range violations (`ERR_INVALID_REQUEST`, with
    `ERR_PAGINATION_INVALID` covering list-endpoint limit and offset
    violations)."
    PRD §3.3: "The draft carries `agreement_id`, `side` (`EMPLOYER` or
    `UNION`), `title`, `proposal_type` (`ECONOMIC` or `NON_ECONOMIC`)"

    Design: Corner/entities/proposal_side_invalid_enum_returns_400
    """
    union = create_union(name="Union CE")
    agreement = create_draft_agreement(union["id"], title="CBA CE")
    payload = create_proposal_payload(
        agreement_id=agreement["id"],
        side="MIDDLE",
        title="Bad enum",
        proposal_type="NON_ECONOMIC",
    )
    resp = api.create_proposal(payload, NEG1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner: entities / proposal_wage_pct_range_boundary
# ---------------------------------------------------------------------------

def test_proposal_wage_pct_inclusive_upper_bound(api):
    """PRD §3.3: "The `wage_increase_pct` is a decimal fraction in the range 0
    to 0.25 inclusive and may be null"

    Design: Corner/entities/proposal_wage_pct_range_boundary
    """
    union = create_union(name="Union CF")
    agreement = create_draft_agreement(union["id"], title="CBA CF")
    ok = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"],
                side="EMPLOYER",
                title="Max ok",
                proposal_type="ECONOMIC",
                wage_increase_pct=0.25,
                affected_headcount=10,
            ),
            NEG1,
        )
    )
    assert ok["wage_increase_pct"] == pytest.approx(0.25)
    resp = api.create_proposal(
        create_proposal_payload(
            agreement_id=agreement["id"],
            side="EMPLOYER",
            title="Too big",
            proposal_type="ECONOMIC",
            wage_increase_pct=0.26,
            affected_headcount=10,
        ),
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
