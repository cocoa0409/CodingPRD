"""Role-based access control: endpoint role exclusivity and abstraction ownership.

The role check runs before existence, so even calls carrying bogus identifiers are
rejected with ERR_INSUFFICIENT_PERMISSIONS when the role is wrong.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_abstraction_payload,
    create_certify_payload,
    create_sample_payload,
    make_abstractor_headers,
    receive_chases,
    setup_hybrid_sample,
    validate_error,
    get_success_data,
)

ABSTRACTOR = TEST_USERS["abstractor_headers"]
OVERREADER = TEST_USERS["overreader_headers"]
RELATIONS = TEST_USERS["provider_relations_headers"]
DIRECTOR = TEST_USERS["quality_director_headers"]


class TestRoleExclusiveDenial:
    def test_abstractor_cannot_draw_sample(self, api):
        """POST /hedis/samples is exclusive to QualityAnalyst; the role check fires
        before existence, so even a bogus run_id yields 403.

        PRD §2.1: "A request whose role is not listed among the roles authorized for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "POST | `/hedis/samples` | Draw the systematic hybrid sample for a
        run; auto-mints one chart chase per sampled member | QualityAnalyst"

        Design: Corner/rbac/abstractor_cannot_draw_sample
        """
        resp = api.create_sample(
            create_sample_payload(NON_EXISTENT_UUID), ABSTRACTOR
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_overreader_cannot_create_abstraction(self, api):
        """POST /hedis/abstractions is exclusive to Abstractor.

        PRD §2.1: "A request whose role is not listed among the roles authorized for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "POST | `/hedis/abstractions` | Create an abstraction on a `RECEIVED`
        chase; author recorded from the caller | Abstractor"

        Design: Corner/rbac/overreader_cannot_create_abstraction
        """
        resp = api.create_abstraction(
            create_abstraction_payload(NON_EXISTENT_UUID, "HIT"), OVERREADER
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_providerrelations_cannot_certify_run(self, api):
        """Certification is exclusive to QualityDirector; ProviderRelations is
        denied before any state evaluation.

        PRD §2.1: "A request whose role is not listed among the roles authorized for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "POST | `/hedis/measure-runs/{runId}/certify` | Director certification
        decision (`SUBMITTED` → `CERTIFIED` or `CERTIFICATION_FAILED`) |
        QualityDirector"

        Design: Corner/rbac/providerrelations_cannot_certify_run
        """
        resp = api.certify_run(
            NON_EXISTENT_UUID, create_certify_payload("CERTIFIED"), RELATIONS
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_qualitydirector_cannot_screen_batch(self, api):
        """Supplemental screening is exclusive to QualityAnalyst; the certification
        role has no data-operations rights.

        PRD §2.1: "A request whose role is not listed among the roles authorized for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "POST | `/hedis/supplemental-batches/{batchId}/screen` | Screen
        records: member matching per variant, measurement-year window, duplicates
        (`RECEIVED` → `SCREENED`) | QualityAnalyst"

        Design: Corner/rbac/qualitydirector_cannot_screen_batch
        """
        resp = api.screen_batch(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_abstractor_cannot_submit_others_abstraction(self, api):
        """Beyond role membership, abstraction mutations enforce row ownership:
        abs-2 cannot submit abs-1's DRAFT.

        PRD §2.8: "Third, abstractions are author-owned rows: editing a draft's
        `result`, submitting, and retracting an abstraction all require `X-User-ID` to
        equal the abstraction's `abstractor_user_id`, and a violation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/abstractor_cannot_submit_others_abstraction
        """
        scenario = setup_hybrid_sample(api, member_refs=("M001",), floor=1)
        c1 = scenario["chases"][0]
        receive_chases(api, [c1])
        a1 = get_success_data(
            api.create_abstraction(
                create_abstraction_payload(c1["id"], "HIT"),
                make_abstractor_headers("abs-1"),
            )
        )
        assert a1["abstractor_user_id"] == "abs-1"
        resp = api.submit_abstraction(a1["id"], make_abstractor_headers("abs-2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
