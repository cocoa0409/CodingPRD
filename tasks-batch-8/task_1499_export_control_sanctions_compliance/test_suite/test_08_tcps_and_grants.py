"""Technology control plans and foreign-national access grants: intervals, windows, counts (PRD §2.5, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_access_grant,
    audit_records_for,
    create_access_grant,
    create_active_grant,
    create_approved_grant,
    create_classified_product,
    create_product,
    create_tcp,
    get_access_grant,
    get_party,
    get_success_data,
    review_access_grant,
    set_clock,
    set_tcp_status,
    setup_active_tcp,
    setup_tcp_with_fn_party,
    validate_error,
    validate_success,
)


class TestTcpStatusCycle:
    def test_tcp_suspend_reinstate_cycle(self, api):
        """PRD §3.8: "Suspension (`to` `SUSPENDED`) is allowed only from `ACTIVE`. Termination (`to` `TERMINATED`) is allowed from `DRAFT`, `ACTIVE`, or `SUSPENDED`, and it cascades to the plan's grants: every grant still `REQUESTED` is denied outright, and every grant in `APPROVED` or `ACTIVE` is revoked, with the party's `active_grant_count` decremented by 1 for each grant that was `ACTIVE`. Any out-of-state target is `ERR_INVALID_STATE`. `TERMINATED` is terminal; the suspend–reinstate cycle may repeat freely within the overlap constraint."

        Design: Corner/state_machines/tcp_suspend_reinstate_cycle
        """
        _, tcp = setup_active_tcp(enclave_id="LAB-S")
        suspended = set_tcp_status(tcp["id"], "SUSPENDED")
        assert suspended["status"] == "SUSPENDED"
        reinstated = set_tcp_status(tcp["id"], "ACTIVE")
        assert reinstated["status"] == "ACTIVE", (
            f"SUSPENDED -> ACTIVE reinstatement must succeed, got {reinstated['status']}"
        )


class TestTcpOverlap:
    def _setup_shared_endpoint_tcps(self):
        """TCP-A ACTIVE [2026-01-01, 2026-06-30]; TCP-B DRAFT [2026-06-30, 2026-12-31];
        both on enclave LAB-7 (closed intervals share the endpoint date 2026-06-30)."""
        product, _ = create_classified_product(
            sku="P-960", name="Gyroscope", controlled_content_pct=20, unit_value_cents=5000,
            classification_code="7A003",
        )
        tcp_a = create_tcp(product["id"], name="TCP-A", enclave_id="LAB-7",
                           segregation_level="LEVEL_2", effective_from="2026-01-01",
                           effective_to="2026-06-30")
        tcp_a = set_tcp_status(tcp_a["id"], "ACTIVE")
        tcp_b = create_tcp(product["id"], name="TCP-B", enclave_id="LAB-7",
                           segregation_level="LEVEL_1", effective_from="2026-06-30",
                           effective_to="2026-12-31")
        return tcp_a, tcp_b

    def test_tcp_activation_shared_endpoint_date_conflicts(self, api, analyst_headers):
        """PRD §3.8: "Activation (`to` `ACTIVE`) is allowed from `DRAFT` or `SUSPENDED` and carries two checks: no other plan on the same `enclave_id` may sit in `ACTIVE` or `SUSPENDED` with an effective window that overlaps under closed-interval semantics — a shared endpoint date counts as overlap — else `ERR_TCP_PERIOD_OVERLAP`; and activation from `DRAFT` additionally requires the covered product to be `CLASSIFIED`, else `ERR_CLASSIFICATION_REQUIRED`."

        Design: Difficulty/resource_temporal_overlap/tcp_closed_interval_shared_endpoint_conflicts
        """
        _, tcp_b = self._setup_shared_endpoint_tcps()

        res = api.set_tcp_status(tcp_b["id"], {"to": "ACTIVE"}, analyst_headers)
        validate_error(res, ApiErrorId.ERR_TCP_PERIOD_OVERLAP)

        after = get_success_data(api.get_tcp(tcp_b["id"], analyst_headers))
        assert after["status"] == "DRAFT", (
            f"rejected activation must leave TCP-B DRAFT, got {after['status']}"
        )

    def test_existing_tcp_unaffected_by_overlap_rejection(self, api, analyst_headers):
        """PRD §3.8: "no other plan on the same `enclave_id` may sit in `ACTIVE` or `SUSPENDED` with an effective window that overlaps under closed-interval semantics — a shared endpoint date counts as overlap — else `ERR_TCP_PERIOD_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/tcp_closed_interval_shared_endpoint_conflicts
        """
        tcp_a, tcp_b = self._setup_shared_endpoint_tcps()

        res = api.set_tcp_status(tcp_b["id"], {"to": "ACTIVE"}, analyst_headers)
        validate_error(res, ApiErrorId.ERR_TCP_PERIOD_OVERLAP)

        tcp_a_after = get_success_data(api.get_tcp(tcp_a["id"], analyst_headers))
        assert tcp_a_after["status"] == "ACTIVE", (
            f"the incumbent TCP must be unaffected, got {tcp_a_after['status']}"
        )


class TestGrantGuards:
    def test_grant_activate_from_requested_rejected(self, api, manager_headers):
        """PRD §3.8: "Activation is a separate manager action with its own four-part gate: the grant must be `APPROVED` (else `ERR_INVALID_STATE`); the parent plan must be `ACTIVE` (else `ERR_TCP_INACTIVE`); the current date must fall inside the half-open window — on or after `start_date` and strictly before `end_date` — else `ERR_GRANT_WINDOW_INVALID`; and the party's posture must not be `BLOCKED` (else `ERR_PARTY_BLOCKED`)."

        Design: Corner/state_machines/grant_activate_from_requested_rejected
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-R")
        grant = create_access_grant(tcp["id"], party["id"],
                                    start_date="2026-08-01", end_date="2026-12-01")
        assert grant["status"] == "REQUESTED"

        res = api.activate_access_grant(grant["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_access_grant(grant["id"], headers=manager_headers)
        assert after["status"] == "REQUESTED"

    def test_grant_activate_before_start_date_rejected(self, api, manager_headers):
        """PRD §3.8: "the current date must fall inside the half-open window — on or after `start_date` and strictly before `end_date` — else `ERR_GRANT_WINDOW_INVALID`"
        PRD §2.5: "Before any client sets it, the logical clock starts at exactly `2026-08-01T00:00:00Z` at server startup, and it never falls back to wall-clock time thereafter."

        Design: Corner/validations/grant_activate_before_start_date_rejected
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-W")
        # Default clock date is 2026-08-01; the window starts 2026-09-01.
        grant = create_approved_grant(tcp["id"], party["id"],
                                      start_date="2026-09-01", end_date="2026-12-01")

        res = api.activate_access_grant(grant["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_GRANT_WINDOW_INVALID)

        after = get_access_grant(grant["id"], headers=manager_headers)
        assert after["status"] == "APPROVED", (
            f"rejected activation must leave the grant APPROVED, got {after['status']}"
        )

    def test_grant_for_non_foreign_national_rejected(self, api, analyst_headers):
        """PRD §3.8: "Two eligibility checks gate creation: the party's `is_foreign_national` must be true (else `ERR_FOREIGN_NATIONAL_REQUIRED`), and the party's `screening_posture` must not be `BLOCKED` (else `ERR_PARTY_BLOCKED`)."

        Design: Corner/validations/grant_for_non_foreign_national_rejected
        """
        product = create_product(sku="P-043", name="Card", controlled_content_pct=0,
                                 unit_value_cents=10)
        tcp = create_tcp(product["id"], name="TCP-N", enclave_id="LAB-N")  # DRAFT is fine
        domestic = validate_success(
            api.create_party(
                {"legal_name": "John Smith", "country_code": "USA", "city": "Austin",
                 "party_type": "END_USER", "is_foreign_national": False},
                analyst_headers,
            ),
            201,
        )
        res = api.create_access_grant(
            {"tcp_id": tcp["id"], "party_id": domestic["id"],
             "start_date": "2026-08-01", "end_date": "2026-09-01"},
            analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_FOREIGN_NATIONAL_REQUIRED)

    def test_grant_activate_under_suspended_tcp_rejected(self, api, manager_headers):
        """PRD §3.8: "the parent plan must be `ACTIVE` (else `ERR_TCP_INACTIVE`)"

        Design: Corner/validations/grant_activate_under_suspended_tcp_rejected
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-S2")
        grant = create_approved_grant(tcp["id"], party["id"],
                                      start_date="2026-08-01", end_date="2026-12-01")
        set_tcp_status(tcp["id"], "SUSPENDED")  # suspend between approval and activation

        res = api.activate_access_grant(grant["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_TCP_INACTIVE)

        after = get_access_grant(grant["id"], headers=manager_headers)
        assert after["status"] == "APPROVED", (
            f"rejected activation must leave the grant APPROVED, got {after['status']}"
        )


class TestGrantOverlapSemantics:
    def test_overlapping_grant_approve_rejected(self, api, manager_headers):
        """PRD §3.8: "A `decision` of `APPROVE` additionally enforces the no-double-access rule: no other grant with the same `party_id` and `tcp_id` may exist in `APPROVED` or `ACTIVE` status with a half-open-overlapping window, else `ERR_GRANT_PERIOD_OVERLAP`."

        Design: Corner/validations/overlapping_grant_approve_rejected
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-O")
        create_approved_grant(tcp["id"], party["id"],
                              start_date="2026-08-01", end_date="2026-09-01")
        g2 = create_access_grant(tcp["id"], party["id"],
                                 start_date="2026-08-15", end_date="2026-09-15")

        # [08-15, 09-15) vs [08-01, 09-01): 08-15 < 09-01 and 08-01 < 09-15 -> overlap
        res = api.review_access_grant(g2["id"], {"decision": "APPROVE"}, manager_headers)
        validate_error(res, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP)

        after = get_access_grant(g2["id"], headers=manager_headers)
        assert after["status"] == "REQUESTED", (
            f"rejected approval must leave the grant REQUESTED, got {after['status']}"
        )

    def test_adjacent_grant_approved(self, api, manager_headers):
        """PRD §3.8: "The overlap check runs again at activation with precise half-open semantics: two grants for the same party and plan conflict only when the first grant's `start_date` is strictly before the second's `end_date` **and** the second's `start_date` is strictly before the first's `end_date`; windows that merely touch — one's `end_date` equal to the other's `start_date` — do not conflict."

        Design: Difficulty/resource_temporal_overlap/grant_half_open_adjacent_intervals_allowed
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-9")
        create_active_grant(tcp["id"], party["id"],
                            start_date="2026-08-01", end_date="2026-09-01")
        g2 = create_access_grant(tcp["id"], party["id"],
                                 start_date="2026-09-01", end_date="2026-10-01")

        # 09-01 < 09-01 is false, so the touching windows do not conflict.
        approved = review_access_grant(g2["id"], "APPROVE", headers=manager_headers)
        assert approved["status"] == "APPROVED", (
            f"adjacent half-open windows must approve cleanly, got {approved['status']}"
        )
        assert_access_grant(approved)

    def test_existing_grant_and_count_unchanged_by_adjacent_approval(self, api, manager_headers):
        """PRD §3.8: "windows that merely touch — one's `end_date` equal to the other's `start_date` — do not conflict."
        PRD §3.8: "Activation increments the party's `active_grant_count` by 1 and writes an audit record of type `GRANT_ACTIVATED`."

        Design: Difficulty/resource_temporal_overlap/grant_half_open_adjacent_intervals_allowed
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-9")
        g1 = create_active_grant(tcp["id"], party["id"],
                                 start_date="2026-08-01", end_date="2026-09-01")
        g2 = create_access_grant(tcp["id"], party["id"],
                                 start_date="2026-09-01", end_date="2026-10-01")
        review_access_grant(g2["id"], "APPROVE", headers=manager_headers)

        g1_after = get_access_grant(g1["id"], headers=manager_headers)
        assert g1_after["status"] == "ACTIVE", (
            f"the incumbent grant must stay ACTIVE, got {g1_after['status']}"
        )
        party_after = get_party(party["id"], headers=manager_headers)
        assert party_after["active_grant_count"] == 1, (
            f"only the activated grant counts; approval alone adds nothing, "
            f"got {party_after['active_grant_count']}"
        )


class TestGrantCountConservation:
    def _setup(self):
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-11")
        grant = create_approved_grant(tcp["id"], party["id"],
                                      start_date="2026-08-01", end_date="2026-12-01")
        return party, grant

    def test_grant_count_increment_then_decrement(self, api, manager_headers):
        """PRD §3.8: "Activation increments the party's `active_grant_count` by 1 and writes an audit record of type `GRANT_ACTIVATED`. A manager may revoke an `ACTIVE` grant, which decrements `active_grant_count` by 1 and writes `GRANT_REVOKED`."

        Design: Difficulty/compensating_invariant/party_active_grant_count_conserved_across_activate_revoke
        """
        party, grant = self._setup()

        activated = get_success_data(api.activate_access_grant(grant["id"], manager_headers))
        assert activated["status"] == "ACTIVE"
        assert get_party(party["id"], headers=manager_headers)["active_grant_count"] == 1, (
            "activation must increment active_grant_count by 1"
        )

        revoked = get_success_data(api.revoke_access_grant(grant["id"], manager_headers))
        assert revoked["status"] == "REVOKED"
        assert get_party(party["id"], headers=manager_headers)["active_grant_count"] == 0, (
            "revoke compensates the activate exactly; count must return to 0"
        )

    def test_grant_activate_revoke_audit_records(self, api, manager_headers, director_headers):
        """PRD §3.8: "Activation increments the party's `active_grant_count` by 1 and writes an audit record of type `GRANT_ACTIVATED`. A manager may revoke an `ACTIVE` grant, which decrements `active_grant_count` by 1 and writes `GRANT_REVOKED`."

        Design: Difficulty/compensating_invariant/party_active_grant_count_conserved_across_activate_revoke
        """
        party, grant = self._setup()
        get_success_data(api.activate_access_grant(grant["id"], manager_headers))
        get_success_data(api.revoke_access_grant(grant["id"], manager_headers))

        activated_records = audit_records_for("AccessGrant", grant["id"],
                                              event_type="GRANT_ACTIVATED",
                                              headers=director_headers)
        revoked_records = audit_records_for("AccessGrant", grant["id"],
                                            event_type="GRANT_REVOKED",
                                            headers=director_headers)
        assert len(activated_records) == 1, (
            f"one GRANT_ACTIVATED record expected, got {len(activated_records)}"
        )
        assert len(revoked_records) == 1, (
            f"one GRANT_REVOKED record expected, got {len(revoked_records)}"
        )


class TestGrantExpirySweep:
    def test_grant_expiry_sweep_exclusive_end_date(self, api, manager_headers):
        """PRD §2.5: "Every `AccessGrant` in `ACTIVE` status whose `end_date` is on or before the current date transitions to `EXPIRED`, and the affected `Party.active_grant_count` is decremented by 1 for each expired grant. Note the asymmetry between the two comparisons, which is deliberate: a license expires only once the current date has passed its last valid day, whereas a grant lapses the moment the current date reaches its exclusive end date."

        Design: Corner/cross_cutting_layers/grant_expiry_sweep_exclusive_end_date
        """
        _, tcp, party = setup_tcp_with_fn_party(enclave_id="LAB-E")
        grant = create_active_grant(tcp["id"], party["id"],
                                    start_date="2026-08-01", end_date="2026-09-01")

        set_clock("2026-08-31T00:00:00Z")
        pre = get_access_grant(grant["id"], headers=manager_headers)
        assert pre["status"] == "ACTIVE", (
            f"2026-08-31 < end_date 2026-09-01: grant must stay ACTIVE, got {pre['status']}"
        )

        set_clock("2026-09-01T00:00:00Z")
        post = get_access_grant(grant["id"], headers=manager_headers)
        assert post["status"] == "EXPIRED", (
            f"2026-09-01 >= end_date (exclusive end): sweep must expire it, got {post['status']}"
        )
        assert get_party(party["id"], headers=manager_headers)["active_grant_count"] == 0
