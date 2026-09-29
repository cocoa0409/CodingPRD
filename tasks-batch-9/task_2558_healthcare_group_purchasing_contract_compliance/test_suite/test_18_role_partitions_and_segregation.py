"""Who may act, whose data they may touch, and the two gates keyed on identity.

Six roles that are peers rather than a ladder, so every exclusive write is
refused to the five others and one shared route is split by a discriminator in
its own body; an entity-backed role whose ownership check has to walk a path
identifier to a member foreign key that never appears in the request; the two
segregation-of-duties pairs, one bound to the endorser of a custom price and one
bound to whoever submitted an evidence dossier most recently; and the single
endpoint that needs no identity at all and refuses nobody.
"""

from typing import Any, Dict, List, Tuple

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_MEMBER_SCOPE_VIOLATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.constants import (
    FLAT_TIER_LADDER,
    HOLDBACK_FLAT,
    ROLE_CLINICAL_REVIEWER,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_CONTRACT_MANAGER,
    ROLE_DISTRIBUTOR_AGENT,
    ROLE_FINANCE_ADMINISTRATOR,
    ROLE_MEMBER_MATERIALS_MANAGER,
    TIER_0,
)
from test_helpers.fixtures import (
    countersign_commitment,
    create_active_contract,
    create_approved_cross_reference,
    create_commitment,
    create_contract,
    create_evidence_review,
    create_item,
    create_local_exception,
    create_member,
    read_activation,
    read_commitment,
    read_contract,
    read_evidence_review,
    read_member,
    set_clock,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_1,
    CLINICAL_REVIEWER_2,
    COMPLIANCE_ANALYST_1,
    CONTRACT_MANAGER_1,
    CONTRACT_MANAGER_2,
    DISTRIBUTOR_AGENT_1,
    FINANCE_ADMINISTRATOR_1,
    UNOWNED_MEMBER_USER_ID,
    anonymous_headers,
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
    distributor_agent_headers,
    finance_administrator_headers,
    headers_for_role,
    make_member_materials_manager_headers,
)

Json = Dict[str, Any]

LEAKAGE_WINDOW = f.leakage_window("2026-08-01", "2026-09-01")


# ---------------------------------------------------------------------------
# The six roles are peers: every exclusive operation is closed to the other five
# ---------------------------------------------------------------------------


@pytest.fixture
def peer_role_setup(api) -> Json:
    """An ACTIVE contract with one item, plus a member holding a live commitment."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-RB",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    item = create_item(api, contract["id"])
    member = create_member(api)
    commitment = create_commitment(api, member["id"], contract["id"])
    countersign_commitment(api, commitment["id"], member["id"], signer_name="Dana Whitfield")
    return {
        "contract": contract,
        "item": item,
        "member": member,
        "commitment": commitment,
    }


def _exclusive_operation_refusals(api, setup: Json) -> List[Tuple[str, Any]]:
    """One exclusive write per role, each attempted by a peer role that owns it not."""
    contract_id = setup["contract"]["id"]
    member_id = setup["member"]["id"]
    return [
        (
            "register a contract as ComplianceAnalyst",
            api.create_contract(
                f.contract_payload(
                    contract_code="C-NO",
                    requires_clinical_review=False,
                    tiers=FLAT_TIER_LADDER,
                    holdback_tiers=HOLDBACK_FLAT,
                ),
                headers=compliance_analyst_headers(),
            ),
        ),
        (
            "suspend a member as ContractManager",
            api.suspend_member(
                member_id,
                f.reason_payload("audit hold"),
                headers=contract_manager_headers(),
            ),
        ),
        (
            "elect a commitment as ContractManager",
            api.create_commitment(
                f.commitment_payload(member_id, contract_id, effective_from="2026-09-01"),
                headers=contract_manager_headers(),
            ),
        ),
        (
            "submit a distributor file as FinanceAdministrator",
            api.create_distributor_file(
                f.distributor_file_payload(
                    member_id,
                    contract_id,
                    [f.purchase_line_row("MI-1", 10, 10000, "2026-08-05")],
                    distributor_code="DIST-MW",
                ),
                headers=finance_administrator_headers(),
            ),
        ),
        (
            "open a fee distribution as ComplianceAnalyst",
            api.create_distribution(
                f.distribution_payload(contract_id), headers=compliance_analyst_headers()
            ),
        ),
        (
            "submit an evidence dossier as ContractManager",
            api.create_evidence_review(
                f.evidence_review_payload(contract_id, 8.00, 7.00, 6.00, summary=None),
                headers=contract_manager_headers(),
            ),
        ),
    ]


def _wrong_track_refusals(api, setup: Json) -> List[Tuple[str, Any]]:
    """The shared activation route, asked for the track that belongs to the other role."""
    commitment_id = setup["commitment"]["id"]
    item_id = setup["item"]["id"]
    member_id = setup["member"]["id"]
    return [
        (
            "TIER_PRICE as MemberMaterialsManager",
            api.create_price_activation(
                f.price_activation_payload(
                    commitment_id,
                    item_id,
                    activation_type="TIER_PRICE",
                    effective_to="2026-08-31",
                ),
                headers=make_member_materials_manager_headers(member_id),
            ),
        ),
        (
            "LOCAL_EXCEPTION as ContractManager",
            api.create_price_activation(
                f.price_activation_payload(
                    commitment_id,
                    item_id,
                    activation_type="LOCAL_EXCEPTION",
                    effective_to="2026-08-31",
                    requested_price_cents=9000,
                ),
                headers=contract_manager_headers(),
            ),
        ),
    ]


def _portfolio_size(api) -> int:
    contracts, meta = validate_paginated(
        api.list_contracts(f.page(100, 0), headers=contract_manager_headers())
    )
    assert len(contracts) == meta["total_count"]
    return meta["total_count"]


class TestExclusiveOperationsAreClosedToPeerRoles:
    """No role subsumes another, so each exclusive write refuses all five peers."""

    def test_six_exclusive_writes_each_refuse_a_peer_role(self, api, peer_role_setup):
        """One operation per role, attempted by a role that does not own it.

        PRD §2.1: "A request whose `X-User-Role` header is missing, is not one of the six role names above, or names a role that the requested operation does not admit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.9: "**Role admission** — `X-User-Role` present, one of the six declared roles, and permitted for the requested operation; otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.1: "A `ContractManager` opens the portfolio by registering a supplier contract."
        PRD §3.3: "A `ComplianceAnalyst` may suspend a member, optionally recording a `reason`, which moves `status` to `SUSPENDED` and increments `version` by one."
        PRD §3.4: "Electing is a `MemberMaterialsManager` action, and its payload names `member_id`, `contract_id`, `elected_tier_code`, `committed_volume_units`, and `effective_from`."
        PRD §3.7: "A `DistributorAgent` submits one **sales-tracing file** per member, contract, distributor and half-open period, naming `member_id`, `contract_id`, a `distributor_code` of 1 to 40 characters, `period_start` and `period_end`, and an array `lines` of at least one entry."
        PRD §3.9: "A `FinanceAdministrator` opens a distribution naming `contract_id`, `period_start` and `period_end`."
        PRD §3.2: "That is the job of the **clinical evidence dossier**, and a `ClinicalReviewer` owns it end to end."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        for label, response in _exclusive_operation_refusals(api, peer_role_setup):
            error = validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
            assert error["error_id"] == ERR_ROLE_NOT_PERMITTED, label

    def test_the_shared_activation_route_is_partitioned_by_its_own_body(
        self, api, peer_role_setup
    ):
        """Both tracks POST the same path; the discriminator decides who may ask.

        PRD §3.6: "A `TIER_PRICE` activation is a GPO-driven contract price and may only be requested by a `ContractManager`."
        PRD §3.6: "A `LOCAL_EXCEPTION` is a member-requested custom price and may only be requested by a `MemberMaterialsManager` whose `X-User-ID` equals the commitment's `member_id`."
        PRD §3.6: "A role that requests the wrong track receives `ERR_ROLE_NOT_PERMITTED`; a member manager reaching for another member's commitment receives `ERR_MEMBER_SCOPE_VIOLATION`."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        refusals = _wrong_track_refusals(api, peer_role_setup)
        assert [label for label, _ in refusals] == [
            "TIER_PRICE as MemberMaterialsManager",
            "LOCAL_EXCEPTION as ContractManager",
        ]
        for label, response in refusals:
            error = validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
            assert error["error_id"] == ERR_ROLE_NOT_PERMITTED, label

    def test_the_leakage_report_is_the_one_read_a_role_can_be_refused(
        self, api, peer_role_setup
    ):
        """The same DistributorAgent that cannot read the report reads the commitment.

        PRD §2.1: "Read access is broad — all six roles may read every collection and every single resource — with one deliberate exception: the leakage report is a member-facing compliance artifact readable only by `ComplianceAnalyst`, `ContractManager`, and `MemberMaterialsManager`, and a `ClinicalReviewer`, `DistributorAgent`, or `FinanceAdministrator` asking for it receives `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        commitment_id = peer_role_setup["commitment"]["id"]
        refused = api.get_leakage_report(
            commitment_id, LEAKAGE_WINDOW, headers=distributor_agent_headers()
        )
        validate_error(refused, ERR_ROLE_NOT_PERMITTED, 403)

        shared = validate_success(
            api.get_commitment(commitment_id, headers=distributor_agent_headers()), 200
        )
        assert shared["id"] == commitment_id
        assert shared["election_status"] == "ACTIVE"

    def test_no_refused_call_left_a_side_effect(self, api, peer_role_setup):
        """Eight refusals, and afterwards the portfolio looks exactly as it did.

        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the first violation, so a later rung's error can never mask an earlier rung's error."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page."
        PRD §3.3: "A new member is `ACTIVE`, with `watchlist_status` `NONE` and `fee_credit_balance_cents` zero."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        member_id = peer_role_setup["member"]["id"]
        before = _portfolio_size(api)
        assert before == 1

        for label, response in _exclusive_operation_refusals(api, peer_role_setup):
            assert validate_error(response, ERR_ROLE_NOT_PERMITTED, 403), label
        for label, response in _wrong_track_refusals(api, peer_role_setup):
            assert validate_error(response, ERR_ROLE_NOT_PERMITTED, 403), label
        validate_error(
            api.get_leakage_report(
                peer_role_setup["commitment"]["id"],
                LEAKAGE_WINDOW,
                headers=distributor_agent_headers(),
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        assert _portfolio_size(api) == before
        member = read_member(api, member_id)
        assert member["status"] == "ACTIVE"
        assert member["version"] == peer_role_setup["member"]["version"]

        for lister in (
            api.list_price_activations,
            api.list_distributor_files,
            api.list_distributions,
            api.list_evidence_reviews,
        ):
            rows, meta = validate_paginated(
                lister(f.page(100, 0), headers=contract_manager_headers())
            )
            assert rows == []
            a.assert_page_meta(meta, limit=100, offset=0, total_count=0, has_more=False)


# ---------------------------------------------------------------------------
# The entity-backed role is scoped through the path, not through the body
# ---------------------------------------------------------------------------


@pytest.fixture
def two_member_setup(api) -> Json:
    """One ACTIVE contract and two members, each holding its own commitment."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-SC",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    member_a = create_member(api, member_code="M-A")
    member_b = create_member(api, member_code="M-B", name="Lakeside Surgical Center")
    commitment_a = create_commitment(api, member_a["id"], contract["id"])
    commitment_b = create_commitment(api, member_b["id"], contract["id"])
    return {
        "contract": contract,
        "member_a": member_a,
        "member_b": member_b,
        "commitment_a": commitment_a,
        "commitment_b": commitment_b,
    }


class TestOneMemberCannotReachAnotherMembersResources:
    """The scope check walks a path identifier to a member key the request never names."""

    def test_a_member_reads_its_own_report_even_over_an_empty_window(
        self, api, two_member_setup
    ):
        """No purchase data at all, so the projection is an empty but legitimate read.

        PRD §3.7: "A `ComplianceAnalyst`, a `ContractManager`, or the owning `MemberMaterialsManager` may request a read-only leakage projection for one commitment over a half-open window supplied as `from_date` and `to_date`, with `to_date` required to be strictly after `from_date`, else `ERR_EFFECTIVE_WINDOW_INVALID`."
        PRD §3.7: "Its `denominator_cents` is the sum of all three of those figures — note that this denominator **always** includes unmatched spend, which is not true of the preliminary compliance variant in §3.8, because the report is a spend view rather than a settlement view."
        PRD §3.7: "The response also echoes `commitment_id`, `from_date` and `to_date`."

        Design: Corner/rbac/member_materials_manager_cannot_read_another_members_leakage_report
        """
        member_a = two_member_setup["member_a"]
        commitment_a = two_member_setup["commitment_a"]

        report = validate_success(
            api.get_leakage_report(
                commitment_a["id"],
                LEAKAGE_WINDOW,
                headers=make_member_materials_manager_headers(member_a["id"]),
            ),
            200,
        )
        assert report["commitment_id"] == commitment_a["id"]
        a.assert_cents(report["denominator_cents"])
        assert report["denominator_cents"] == 0
        assert report["from_date"] == "2026-08-01"
        assert report["to_date"] == "2026-09-01"

    def test_reading_another_members_report_is_a_scope_violation(self, api, two_member_setup):
        """The refused read names only a commitment id; the member key is derived.

        PRD §2.1: "`MemberMaterialsManager` is different: it is entity-backed."
        PRD §2.1: "Concretely, a `MemberMaterialsManager` may only elect a commitment whose `member_id` equals its own `X-User-ID`, may only propose a cross-reference for its own `member_id`, may only sign the letter of participation of a commitment whose `member_id` equals its `X-User-ID`, may only request a local pricing exception on a commitment it owns, and may only read the leakage report of a commitment it owns."
        PRD §2.1: "Any of these performed against another member's resource is rejected with `ERR_MEMBER_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.9: "**Member scope** — for the entity-backed `MemberMaterialsManager`, `X-User-ID` must equal the member the operation touches: the body `member_id` on a create, or the `member_id` reachable from the path resource otherwise."

        Design: Corner/rbac/member_materials_manager_cannot_read_another_members_leakage_report
        """
        member_a = two_member_setup["member_a"]
        commitment_b = two_member_setup["commitment_b"]

        refused = api.get_leakage_report(
            commitment_b["id"],
            LEAKAGE_WINDOW,
            headers=make_member_materials_manager_headers(member_a["id"]),
        )
        validate_error(refused, ERR_MEMBER_SCOPE_VIOLATION, 403)

    def test_an_opaque_role_reads_both_members_reports(self, api, two_member_setup):
        """The endpoint itself is not restricted; the caller's identity model is.

        PRD §2.1: "Five of the six roles are operator roles whose identity is opaque."
        PRD §2.1: "When `X-User-Role` is `ContractManager`, `ClinicalReviewer`, `ComplianceAnalyst`, `DistributorAgent`, or `FinanceAdministrator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity."
        PRD §3.7: "A `ComplianceAnalyst`, a `ContractManager`, or the owning `MemberMaterialsManager` may request a read-only leakage projection for one commitment over a half-open window supplied as `from_date` and `to_date`, with `to_date` required to be strictly after `from_date`, else `ERR_EFFECTIVE_WINDOW_INVALID`."

        Design: Corner/rbac/member_materials_manager_cannot_read_another_members_leakage_report
        """
        seen = []
        for commitment in (two_member_setup["commitment_a"], two_member_setup["commitment_b"]):
            report = validate_success(
                api.get_leakage_report(
                    commitment["id"], LEAKAGE_WINDOW, headers=compliance_analyst_headers()
                ),
                200,
            )
            seen.append(report["commitment_id"])
        assert seen == [
            two_member_setup["commitment_a"]["id"],
            two_member_setup["commitment_b"]["id"],
        ]

    def test_replacing_another_members_item_master_is_refused(self, api, two_member_setup):
        """The member identifier is in the path, and that is where the scope is read.

        PRD §2.1: "Replacing a member's item master is scoped the same way, through the member identifier carried in the path."
        PRD §3.3: "The item master is the member's own catalogue of the things it buys, and only the member curates it: a `MemberMaterialsManager` replaces its own `item_master` wholesale, which increments that member's `version` by one."

        Design: Corner/rbac/member_materials_manager_cannot_read_another_members_leakage_report
        """
        member_a = two_member_setup["member_a"]
        member_b = two_member_setup["member_b"]

        refused = api.patch_member_item_master(
            member_b["id"],
            f.item_master_payload(
                [f.item_master_row("MI-9", description="Injected by the wrong member")]
            ),
            headers=make_member_materials_manager_headers(member_a["id"]),
        )
        validate_error(refused, ERR_MEMBER_SCOPE_VIOLATION, 403)

        after = read_member(api, member_b["id"])
        assert [row["member_item_number"] for row in after["item_master"]] == ["MI-1"]
        assert after["version"] == member_b["version"]

    def test_signing_another_members_letter_is_refused(self, api, two_member_setup):
        """A nested action path is scoped exactly like a top-level one.

        PRD §3.4: "The member's own `MemberMaterialsManager` then signs it, supplying `signer_name` in the request, which advances `lop_status` from `ISSUED` to `SIGNED` and stores that name; a manager whose `X-User-ID` is not the commitment's `member_id` is refused with `ERR_MEMBER_SCOPE_VIOLATION`."
        PRD §2.9: "This rung guards exactly five operations: `POST /gpo/commitments`, `POST /gpo/item-cross-references`, `POST /gpo/price-activations` when `activation_type` is `LOCAL_EXCEPTION`, `POST /gpo/commitments/{commitment_id}/lop/sign`, and `GET /gpo/commitments/{commitment_id}/leakage-report`."
        PRD §3.4: "A newly elected commitment is born with `election_status` `ELECTED`, `lop_status` `NOT_ISSUED`, `signer_name` null, `current_tier_code` null, `requalification_round` zero, `last_final_compliance_pct` null, all three year-to-date ledgers — `ytd_on_contract_spend_cents`, `ytd_total_category_spend_cents` and `ytd_measured_volume_units` — at zero, `ytd_leakage_pct` at 0.00, and `leakage_flag` false."

        Design: Corner/rbac/member_materials_manager_cannot_read_another_members_leakage_report
        """
        member_a = two_member_setup["member_a"]
        commitment_b = two_member_setup["commitment_b"]

        refused = api.sign_lop(
            commitment_b["id"],
            f.signer_payload("Impersonator"),
            headers=make_member_materials_manager_headers(member_a["id"]),
        )
        validate_error(refused, ERR_MEMBER_SCOPE_VIOLATION, 403)

        after = read_commitment(api, commitment_b["id"])
        assert after["lop_status"] == "NOT_ISSUED"
        assert after["signer_name"] is None


# ---------------------------------------------------------------------------
# The custom-price gate: both hops belong to one role, so identity separates them
# ---------------------------------------------------------------------------


@pytest.fixture
def local_exception_setup(api) -> Json:
    """A DRAFT LOCAL_EXCEPTION asking 9000 against a zero-discount tier price of 10000."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-SD",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    item = create_item(api, contract["id"])
    member = create_member(api)
    commitment = create_commitment(api, member["id"], contract["id"])
    countersign_commitment(api, commitment["id"], member["id"], signer_name="Dana Whitfield")
    create_approved_cross_reference(api, member["id"], item["id"])
    activation = create_local_exception(
        api,
        commitment["id"],
        member["id"],
        item["id"],
        9000,
        effective_to="2026-08-31",
        stage="DRAFT",
    )
    return {
        "contract": contract,
        "item": item,
        "member": member,
        "commitment": commitment,
        "activation": activation,
    }


def _endorse(api, activation_id: str, user_id: str) -> Json:
    return validate_success(
        api.endorse_price_activation(
            activation_id, {}, headers=contract_manager_headers(user_id)
        ),
        200,
    )


class TestTheLocalExceptionApproverIsNotItsEndorser:
    """Same role on both hops, so the only separator is the recorded user identifier."""

    def test_the_endorsement_stamps_the_endorsing_manager(self, api, local_exception_setup):
        """A DRAFT row carries neither audit identifier; endorsing writes the first one.

        PRD §3.6: "An accepted request creates the activation in `DRAFT` status with `origin` `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`, `superseded_by_activation_id` and `replaces_activation_id` all null."
        PRD §3.6: "A `ContractManager` first endorses the `DRAFT` row, moving `DRAFT → ENDORSED` and recording `endorsed_by_user_id` as the endorser's `X-User-ID`."

        Design: Corner/rbac/local_exception_approver_cannot_be_the_endorser
        """
        activation = local_exception_setup["activation"]
        assert activation["status"] == "DRAFT"
        assert activation["endorsed_by_user_id"] is None
        assert activation["approved_by_user_id"] is None

        endorsed = _endorse(api, activation["id"], CONTRACT_MANAGER_1)
        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CONTRACT_MANAGER_1
        a.assert_version_bump(endorsed, activation["version"])

    def test_the_endorser_cannot_approve_what_it_endorsed(self, api, local_exception_setup):
        """The approving identity equals the recorded endorser, which is the whole fault.

        PRD §2.1: "Two segregation-of-duties gates are keyed on `X-User-ID` rather than on role."
        PRD §2.1: "The `ClinicalReviewer` who submitted an evidence dossier may not be the `ClinicalReviewer` who endorses it, and the `ContractManager` who endorsed a local pricing exception may not be the `ContractManager` who approves it."
        PRD §2.1: "Either violation returns `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §2.9: "**Segregation of duties** — the endorser of an evidence review is not its submitter, and the approver of a local pricing exception is not its endorser; otherwise `ERR_SEGREGATION_OF_DUTIES` (409)."

        Design: Corner/rbac/local_exception_approver_cannot_be_the_endorser
        """
        activation_id = local_exception_setup["activation"]["id"]
        _endorse(api, activation_id, CONTRACT_MANAGER_1)

        refused = api.approve_price_activation(
            activation_id, {}, headers=contract_manager_headers(CONTRACT_MANAGER_1)
        )
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 409)

    def test_the_refused_approval_leaves_the_row_endorsed(self, api, local_exception_setup):
        """A segregation failure is not a state failure: the row stays approvable.

        PRD §3.6: "A **different** `ContractManager` then approves it, moving `ENDORSED → APPROVED` and recording `approved_by_user_id`; approval requires the row to be in `ENDORSED`, requires the approving `X-User-ID` to differ from `endorsed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and applies the same `REQUAL_REVIEW` bar."
        PRD §2.4: "Ten of the eleven resource types — contracts, contract items, members, clinical evidence reviews, commitments, item cross-references, price activations, distributor files, compliance measurements and administrative fee distributions — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every accepted mutation of that row, including mutations the server performs on its own initiative as part of a cascade."
        PRD §2.1: "Read access is broad — all six roles may read every collection and every single resource — with one deliberate exception: the leakage report is a member-facing compliance artifact readable only by `ComplianceAnalyst`, `ContractManager`, and `MemberMaterialsManager`, and a `ClinicalReviewer`, `DistributorAgent`, or `FinanceAdministrator` asking for it receives `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/local_exception_approver_cannot_be_the_endorser
        """
        activation_id = local_exception_setup["activation"]["id"]
        endorsed = _endorse(api, activation_id, CONTRACT_MANAGER_1)
        validate_error(
            api.approve_price_activation(
                activation_id, {}, headers=contract_manager_headers(CONTRACT_MANAGER_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        seen = validate_success(
            api.get_price_activation(activation_id, headers=compliance_analyst_headers()), 200
        )
        assert seen["status"] == "ENDORSED"
        assert seen["approved_by_user_id"] is None
        assert seen["endorsed_by_user_id"] == CONTRACT_MANAGER_1
        a.assert_version_unchanged(seen, endorsed["version"])

    def test_a_second_manager_approves_and_both_audit_ids_survive(
        self, api, local_exception_setup
    ):
        """The row keeps the endorser it always had and gains a different approver.

        PRD §3.6: "A **different** `ContractManager` then approves it, moving `ENDORSED → APPROVED` and recording `approved_by_user_id`; approval requires the row to be in `ENDORSED`, requires the approving `X-User-ID` to differ from `endorsed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and applies the same `REQUAL_REVIEW` bar."
        PRD §2.1: "The server records it where a workflow demands an audit trail — as `submitted_by_user_id` and `endorsed_by_user_id` on a clinical evidence review, as `approved_by_user_id` on a cross-reference, and as `endorsed_by_user_id` and `approved_by_user_id` on a price activation — and it compares two such recorded identifiers against each other to enforce segregation of duties, but it never compares an opaque identifier to any entity's `id`."

        Design: Corner/rbac/local_exception_approver_cannot_be_the_endorser
        """
        activation_id = local_exception_setup["activation"]["id"]
        _endorse(api, activation_id, CONTRACT_MANAGER_1)
        validate_error(
            api.approve_price_activation(
                activation_id, {}, headers=contract_manager_headers(CONTRACT_MANAGER_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        approved = validate_success(
            api.approve_price_activation(activation_id, {}, headers=contract_manager_2_headers()),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CONTRACT_MANAGER_2
        assert approved["endorsed_by_user_id"] == CONTRACT_MANAGER_1
        assert approved["approved_by_user_id"] != approved["endorsed_by_user_id"]

    def test_the_endorser_may_still_activate_the_approved_row(self, api, local_exception_setup):
        """The separation binds the endorse-and-approve pair only, not the whole ladder.

        PRD §3.6: "Only then may a `ContractManager` activate it, moving `APPROVED → ACTIVE` under exactly the same four preconditions as the tier-price activation — `APPROVED` status with `activation_type` `LOCAL_EXCEPTION`, an `ACTIVE` contract, the evidence gate for an evidence-flagged item, and an `APPROVED` cross-reference — with exactly the same effects: `status` becomes `ACTIVE`, the activation's `version` increments by one, and the catalog item's `active_activation_count` is recomputed with a `version` increment on that item."
        PRD §3.6: "Two illustrations of the interaction: a requested 9000 cents against a zero-discount tier price of 10000 with a floor of 8200 yields a candidate of 9000, which is above the floor, so `computed_price_cents` is 9000 and `price_clamped` is false; a requested 8000 cents against a 1500-basis-point tier price of 8500 with a floor of 8200 yields a candidate of 8000, which is below the floor, so `computed_price_cents` becomes 8200 and `price_clamped` is true."

        Design: Corner/rbac/local_exception_approver_cannot_be_the_endorser
        """
        activation_id = local_exception_setup["activation"]["id"]
        _endorse(api, activation_id, CONTRACT_MANAGER_1)
        validate_error(
            api.approve_price_activation(
                activation_id, {}, headers=contract_manager_headers(CONTRACT_MANAGER_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        validate_success(
            api.approve_price_activation(activation_id, {}, headers=contract_manager_2_headers()),
            200,
        )

        activated = validate_success(
            api.activate_price_activation(
                activation_id, {}, headers=contract_manager_headers(CONTRACT_MANAGER_1)
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert activated["tier_code_at_activation"] == TIER_0
        a.assert_cents(activated["computed_price_cents"])
        assert activated["computed_price_cents"] == 9000
        assert activated["price_clamped"] is False

        reread = read_activation(api, activation_id)
        assert reread["status"] == "ACTIVE"
        assert reread["endorsed_by_user_id"] == CONTRACT_MANAGER_1
        assert reread["approved_by_user_id"] == CONTRACT_MANAGER_2


# ---------------------------------------------------------------------------
# The evidence gate: the blocked endorser moves with the submitter slot
# ---------------------------------------------------------------------------


@pytest.fixture
def evidence_dossier_setup(api) -> Json:
    """A DRAFT contract carrying one dossier submitted by CR-1 at 8.00 / 7.00 / 6.00."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-EV",
        category_code="CAT-MSH",
        requires_clinical_review=True,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    review = create_evidence_review(
        api, contract["id"], 8.00, 7.00, 6.00, summary="Meta-analysis of 14 trials."
    )
    return {"contract": contract, "review": review}


def _request_revision(api, review_id: str, user_id: str, reason: str) -> Json:
    return validate_success(
        api.request_review_revision(
            review_id, f.reason_payload(reason), headers=clinical_reviewer_headers(user_id)
        ),
        200,
    )


class TestTheEvidenceEndorserIsNotTheMostRecentSubmitter:
    """Both terminal acts carry the identity bar; the revision request does not."""

    def test_the_submission_stamps_its_reviewer_and_scores_seven_fifteen(
        self, api, evidence_dossier_setup
    ):
        """The dossier that the rest of this scenario argues over, and its derived verdict.

        PRD §3.2: "A submission names the `contract_id` whose category conversion is under review — the contract must exist and must be in `DRAFT` or `ACTIVE` status — and carries three evidence scores, each between 0.00 and 10.00 with at most two decimal places: `clinical_efficacy_score`, `safety_score`, and `supply_resilience_score`."
        PRD §3.2: "The dossier is created in `UNDER_REVIEW` status with `revision_round` at zero, and its `submitted_by_user_id` is set to the submitting reviewer's `X-User-ID`."
        PRD §3.2: "Worked through: scores of 8.00, 7.00 and 6.00 give 3.20 plus 2.45 plus 1.50, a weighted score of 7.15; scores of 6.50, 7.00 and 6.00 give 2.60 plus 2.45 plus 1.50, a weighted score of 6.55; and scores of 7.00, 7.00 and 7.02 give an unrounded 7.0050 that rounds half up to 7.01."
        PRD §3.2: "From the weighted score the server derives `conversion_recommendation`: it is `CONVERT` when the weighted score is at least 7.00 — the threshold is **inclusive**, so a weighted score of exactly 7.00 recommends conversion — and `DO_NOT_CONVERT` otherwise."

        Design: Corner/rbac/evidence_endorsement_cannot_be_done_by_the_submitting_reviewer
        """
        review = evidence_dossier_setup["review"]
        a.assert_identifier(review["id"])
        assert review["status"] == "UNDER_REVIEW"
        assert review["revision_round"] == 0
        assert review["submitted_by_user_id"] == CLINICAL_REVIEWER_1
        assert review["endorsed_by_user_id"] is None
        a.assert_score(review["weighted_score"], 7.15)
        assert review["conversion_recommendation"] == "CONVERT"

    def test_the_submitter_can_neither_endorse_nor_reject_its_own_dossier(
        self, api, evidence_dossier_setup
    ):
        """Both terminal acts refuse the submitter, and neither moves the dossier.

        PRD §3.2: "The endorsing reviewer's `X-User-ID` must differ from `submitted_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES` — the segregation rung outranks the score rung, so a self-endorsement of an under-threshold dossier reports the segregation violation."
        PRD §3.2: "It requires the same segregation check — the rejecting reviewer must not be the submitter — and returns `ERR_SEGREGATION_OF_DUTIES` when it is."
        PRD §2.1: "Either violation returns `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/rbac/evidence_endorsement_cannot_be_done_by_the_submitting_reviewer
        """
        review = evidence_dossier_setup["review"]

        validate_error(
            api.endorse_review(review["id"], {}, headers=clinical_reviewer_headers()),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        validate_error(
            api.reject_review(
                review["id"],
                f.reason_payload("self-rejection attempt"),
                headers=clinical_reviewer_headers(),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        after = read_evidence_review(api, review["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["submitted_by_user_id"] == CLINICAL_REVIEWER_1
        a.assert_version_unchanged(after, review["version"])

    def test_the_submitter_may_send_its_own_dossier_back_for_revision(
        self, api, evidence_dossier_setup
    ):
        """The cycle hop carries no identity bar, only the round budget.

        PRD §3.2: "From `UNDER_REVIEW`, a reviewer may send it back with a revision request, optionally recording a `reason`; the dossier moves `UNDER_REVIEW → REVISION_REQUESTED` and `revision_round` increments by one."

        Design: Corner/rbac/evidence_endorsement_cannot_be_done_by_the_submitting_reviewer
        """
        review = evidence_dossier_setup["review"]

        sent_back = _request_revision(
            api, review["id"], CLINICAL_REVIEWER_1, "need resilience detail"
        )
        assert sent_back["status"] == "REVISION_REQUESTED"
        assert sent_back["revision_round"] == 1
        assert sent_back["submitted_by_user_id"] == CLINICAL_REVIEWER_1

    def test_the_resubmitting_reviewer_becomes_the_blocked_party(
        self, api, evidence_dossier_setup
    ):
        """The bar tracks the submitter slot, so resubmission hands the block over.

        PRD §3.2: "From `REVISION_REQUESTED`, a resubmission returns the dossier `REVISION_REQUESTED → UNDER_REVIEW`, overwrites the three score fields with the resubmitted values plus an optional replacement `summary`, recomputes `weighted_score` and then `conversion_recommendation` from it, and — this is the part that matters for segregation of duties — sets `submitted_by_user_id` to the resubmitting reviewer's `X-User-ID`, so the endorsement bar always applies to whoever submitted the dossier most recently."
        PRD §3.2: "Resubmission does **not** increment `revision_round`; that counter is consumed only by the revision request."
        PRD §3.2: "The endorsing reviewer's `X-User-ID` must differ from `submitted_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES` — the segregation rung outranks the score rung, so a self-endorsement of an under-threshold dossier reports the segregation violation."

        Design: Corner/rbac/evidence_endorsement_cannot_be_done_by_the_submitting_reviewer
        """
        review = evidence_dossier_setup["review"]
        _request_revision(api, review["id"], CLINICAL_REVIEWER_1, "need resilience detail")

        resubmitted = validate_success(
            api.resubmit_review(
                review["id"],
                f.resubmit_payload(8.00, 7.00, 6.00, summary="Resilience appendix added."),
                headers=clinical_reviewer_2_headers(),
            ),
            200,
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["submitted_by_user_id"] == CLINICAL_REVIEWER_2
        assert resubmitted["revision_round"] == 1
        a.assert_score(resubmitted["weighted_score"], 7.15)

        validate_error(
            api.endorse_review(review["id"], {}, headers=clinical_reviewer_2_headers()),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

    def test_the_handover_frees_the_original_submitter_to_endorse(
        self, api, evidence_dossier_setup
    ):
        """CR-1 was blocked at the start and is admitted once CR-2 owns the submission.

        PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then reaches across to the parent contract: `evidence_endorsed` is recomputed and the contract's `version` increments by one."

        Design: Corner/rbac/evidence_endorsement_cannot_be_done_by_the_submitting_reviewer
        """
        contract = evidence_dossier_setup["contract"]
        review = evidence_dossier_setup["review"]
        _request_revision(api, review["id"], CLINICAL_REVIEWER_1, "need resilience detail")
        validate_success(
            api.resubmit_review(
                review["id"],
                f.resubmit_payload(8.00, 7.00, 6.00, summary="Resilience appendix added."),
                headers=clinical_reviewer_2_headers(),
            ),
            200,
        )

        endorsed = validate_success(
            api.endorse_review(review["id"], {}, headers=clinical_reviewer_headers()), 200
        )
        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_1
        assert endorsed["submitted_by_user_id"] == CLINICAL_REVIEWER_2

        parent = read_contract(api, contract["id"])
        assert parent["evidence_endorsed"] is True
        assert parent["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# The one write no role can be refused, and the read every role shares
# ---------------------------------------------------------------------------


CLOCK_TURNS: List[Tuple[str, str, str]] = [
    (ROLE_CONTRACT_MANAGER, CONTRACT_MANAGER_1, "2026-08-10T00:00:00Z"),
    (ROLE_CLINICAL_REVIEWER, CLINICAL_REVIEWER_1, "2026-08-11T00:00:00Z"),
    (ROLE_COMPLIANCE_ANALYST, COMPLIANCE_ANALYST_1, "2026-08-12T00:00:00Z"),
    # The entity-backed role needs no real member here: the clock resolves no entity.
    (ROLE_MEMBER_MATERIALS_MANAGER, UNOWNED_MEMBER_USER_ID, "2026-08-13T00:00:00Z"),
    (ROLE_DISTRIBUTOR_AGENT, DISTRIBUTOR_AGENT_1, "2026-08-14T00:00:00Z"),
    (ROLE_FINANCE_ADMINISTRATOR, FINANCE_ADMINISTRATOR_1, "2026-08-15T00:00:00Z"),
]


@pytest.fixture
def clock_setup(api) -> Json:
    """A single DRAFT contract, so there is a row to read and a row to watch."""
    contract = create_contract(
        api,
        contract_code="C-CK",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    return {"contract": contract}


class TestTheClockIsSharedByEveryRoleAndReadsAreToo:
    """Three widths of shared access: everyone, everyone, and only three."""

    def test_every_role_in_turn_sets_the_clock(self, api, clock_setup):
        """Six roles, six instants, six echoes of exactly what was stored.

        PRD §2.4: "Time in this system is a **logical clock**, not wall-clock time."
        PRD §2.4: "A test-driving capability sets the clock to an exact instant supplied as `current_utc` and echoes the value it stored back as `current_utc`; all six roles may invoke it, and it modifies no entity."

        Design: Corner/rbac/every_role_may_set_the_logical_clock_and_read
        """
        echoed = []
        for role, user_id, instant in CLOCK_TURNS:
            stored = validate_success(
                api.set_clock(instant, headers=headers_for_role(role, user_id)), 200
            )
            a.assert_instant_equals(stored["current_utc"], instant)
            echoed.append(stored["current_utc"])
        assert len(echoed) == len(CLOCK_TURNS)

    def test_the_clock_needs_no_acting_user_identity(self, api, clock_setup):
        """The one endpoint exempted from the authentication rung, for all six roles.

        PRD §2.1: "A request whose `X-User-ID` header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the single exception is the logical-clock endpoint, which is a test-driving capability and requires no user identity."
        PRD §2.9: "**Authentication** — `X-User-ID` present and non-empty on every request except `POST /gpo/_clock/set_current_utc`; otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/every_role_may_set_the_logical_clock_and_read
        """
        for role, _user_id, instant in CLOCK_TURNS:
            stored = validate_success(
                api.set_clock(instant, headers=anonymous_headers(role)), 200
            )
            a.assert_instant_equals(stored["current_utc"], instant)

    def test_the_clock_is_a_pure_setter(self, api, clock_setup):
        """Six accepted writes to the clock, and not one audit field on any row moves.

        PRD §2.4: "A test-driving capability sets the clock to an exact instant supplied as `current_utc` and echoes the value it stored back as `current_utc`; all six roles may invoke it, and it modifies no entity."
        PRD §2.4: "Ten of the eleven resource types — contracts, contract items, members, clinical evidence reviews, commitments, item cross-references, price activations, distributor files, compliance measurements and administrative fee distributions — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every accepted mutation of that row, including mutations the server performs on its own initiative as part of a cascade."

        Design: Corner/rbac/every_role_may_set_the_logical_clock_and_read
        """
        before = read_contract(api, clock_setup["contract"]["id"])
        for role, user_id, instant in CLOCK_TURNS:
            validate_success(api.set_clock(instant, headers=headers_for_role(role, user_id)), 200)

        after = read_contract(api, clock_setup["contract"]["id"])
        a.assert_version_unchanged(after, before["version"])
        a.assert_instant_equals(after["updated_at"], before["updated_at"])
        a.assert_fields_unchanged(before, after, "status", "version", "updated_at", "created_at")

    def test_a_plain_read_is_shared_by_the_narrowest_roles(self, api, clock_setup):
        """The two roles with the smallest write surface still read the contract.

        PRD §2.1: "Read access is broad — all six roles may read every collection and every single resource — with one deliberate exception: the leakage report is a member-facing compliance artifact readable only by `ComplianceAnalyst`, `ContractManager`, and `MemberMaterialsManager`, and a `ClinicalReviewer`, `DistributorAgent`, or `FinanceAdministrator` asking for it receives `ERR_ROLE_NOT_PERMITTED`."
        PRD §3.1: "Every new contract is born in `DRAFT` status with `evidence_endorsed` false and `active_commitment_count` zero."

        Design: Corner/rbac/every_role_may_set_the_logical_clock_and_read
        """
        contract_id = clock_setup["contract"]["id"]
        for headers in (finance_administrator_headers(), clinical_reviewer_headers()):
            seen = validate_success(api.get_contract(contract_id, headers=headers), 200)
            assert seen["id"] == contract_id
            assert seen["status"] == "DRAFT"
            assert seen["evidence_endorsed"] is False
