"""Fee calculations and derived-field reconciliation: species rate tiers, the
fee cap, pinned per-line rounding, and lifecycle filtering of the permit's
aggregates (PRD §2.7, §3.4, §3.5)."""
from test_helpers import (
    create_draft_certificate,
    create_entry_requirement,
    create_negative_test,
    create_premises,
    create_scheduled_record,
    create_veterinarian,
    get_permit,
    get_premises,
    make_vet_headers,
    set_clock,
    setup_issued_certificate_with_permit,
    validate_success,
)


class TestFeeTierCapCombination:
    def _setup_two_premises(self, api):
        prem_free = create_premises(
            name="Ranch Free", initial_head_count=250, disease_status="ACCREDITED_FREE"
        )
        prem_mon = create_premises(
            name="Ranch Mon", initial_head_count=150, disease_status="MONITORED"
        )
        vet = create_veterinarian()
        create_entry_requirement()  # KS/CATTLE BRUCELLOSIS 30d, vax >= 14d
        test_free = create_negative_test(prem_free["id"], lab_reference="LAB-1")
        test_mon = create_negative_test(prem_mon["id"], lab_reference="LAB-2")
        set_clock("2026-08-10T00:00:00Z")
        cert1 = create_draft_certificate(
            prem_free["id"], vet["id"], head_count=200,
            test_record_id=test_free["id"], vaccination_date="2026-07-12T00:00:00Z",
        )
        cert2 = create_draft_certificate(
            prem_mon["id"], vet["id"], head_count=110,
            test_record_id=test_mon["id"], vaccination_date="2026-07-12T00:00:00Z",
        )
        return vet, cert1, cert2

    def test_cvi_fee_tiered_surcharge_cap_combination_clamped(self, api, admin_headers):
        """PRD §3.4: "The fee is a base of 2500 cents, plus a per-head rate
        multiplied by the certificate's `head_count` — 150 cents for `CATTLE`,
        90 for `SWINE`, 25 for `POULTRY`, 60 for `SHEEP_GOAT`, 200 for `EQUINE`
        — plus a surcharge of 1000 cents when the origin premises'
        `disease_status` is `MONITORED` at the moment of submission, with the
        total capped at 20000 cents (an `ACCREDITED_FREE` premises pays no
        surcharge, and a `QUARANTINE_HOLD` or `INFECTED` premises never reaches
        this point because the disease-hold gate fires first)."

        Design: Difficulty/combinatorial_formula/cvi_fee_tiered_surcharge_cap_combination
        """
        vet, cert1, cert2 = self._setup_two_premises(api)
        resp = api.submit_certificate(cert1["id"], make_vet_headers(vet["id"]))
        data = validate_success(resp, 200)
        # raw = 2500 + 150*200 + 0 = 32500 -> clamped to the 20000 cap.
        assert data["provisional_fee_cents"] == 20000, (
            f"raw 32500 must clamp at FEE_CAP 20000, got {data['provisional_fee_cents']}"
        )

    def test_cvi_fee_tiered_surcharge_cap_combination_exact_boundary(
        self, api, admin_headers
    ):
        """PRD §3.4: "The fee is a base of 2500 cents, plus a per-head rate
        multiplied by the certificate's `head_count` — 150 cents for `CATTLE`,
        90 for `SWINE`, 25 for `POULTRY`, 60 for `SHEEP_GOAT`, 200 for `EQUINE`
        — plus a surcharge of 1000 cents when the origin premises'
        `disease_status` is `MONITORED` at the moment of submission, with the
        total capped at 20000 cents (an `ACCREDITED_FREE` premises pays no
        surcharge, and a `QUARANTINE_HOLD` or `INFECTED` premises never reaches
        this point because the disease-hold gate fires first)."

        Design: Difficulty/combinatorial_formula/cvi_fee_tiered_surcharge_cap_combination
        """
        vet, cert1, cert2 = self._setup_two_premises(api)
        resp = api.submit_certificate(cert2["id"], make_vet_headers(vet["id"]))
        data = validate_success(resp, 200)
        # raw = 2500 + 150*110 + 1000 = 20000 -> lands exactly on the cap.
        assert data["provisional_fee_cents"] == 20000, (
            f"2500 + 16500 + 1000 = 20000 exactly (cap has no clamping effect), "
            f"got {data['provisional_fee_cents']}"
        )


class TestSpeciesRateConstants:
    def test_cvi_fee_species_rate_constants(self, api, admin_headers):
        """PRD §3.4: "The fee is a base of 2500 cents, plus a per-head rate
        multiplied by the certificate's `head_count` — 150 cents for `CATTLE`,
        90 for `SWINE`, 25 for `POULTRY`, 60 for `SHEEP_GOAT`, 200 for
        `EQUINE` — plus a surcharge of 1000 cents when the origin premises'
        `disease_status` is `MONITORED` at the moment of submission, with the
        total capped at 20000 cents".

        Design: Corner/calculations/cvi_fee_species_rate_constants
        """
        prem_s = create_premises(name="Hog Farm", species_code="SWINE", initial_head_count=200)
        prem_p = create_premises(name="Poultry Farm", species_code="POULTRY", initial_head_count=200)
        vet = create_veterinarian()
        create_entry_requirement(none_type=True, species_code="SWINE", permit_required=False)
        create_entry_requirement(none_type=True, species_code="POULTRY", permit_required=False)
        set_clock("2026-08-10T00:00:00Z")
        cert_s = create_draft_certificate(prem_s["id"], vet["id"], species_code="SWINE", head_count=10)
        cert_p = create_draft_certificate(prem_p["id"], vet["id"], species_code="POULTRY", head_count=100)

        vet_h = make_vet_headers(vet["id"])
        fee_s = validate_success(api.submit_certificate(cert_s["id"], vet_h), 200)
        # 2500 + 90*10 + 1000 (MONITORED) = 4400
        assert fee_s["provisional_fee_cents"] == 4400
        fee_p = validate_success(api.submit_certificate(cert_p["id"], vet_h), 200)
        # 2500 + 25*100 + 1000 (MONITORED) = 6000
        assert fee_p["provisional_fee_cents"] == 6000


class TestMovementFeeRates:
    def test_movement_fee_swine_rate_rounding(self, api, admin_headers):
        """PRD §3.5: "its `movement_fee_cents` is computed once, at creation:
        the record's `head_count` multiplied by the per-head movement rate for
        the species resolved through the permit to its certificate — 137.5
        cents for `CATTLE`, 62.5 for `SWINE`, 10.25 for `POULTRY`, 45.5 for
        `SHEEP_GOAT`, 210.75 for `EQUINE` — rounded half up to whole cents per
        the pinned order of §2.7."

        Design: Corner/calculations/movement_fee_swine_rate_rounding
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=10, species="SWINE", premises_name="Hog Farm C4"
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=3)
        # round_half_up(3 * 62.5) = round_half_up(187.5) = 188.
        assert record["movement_fee_cents"] == 188
        assert get_permit(permit["id"])["total_movement_fees_cents"] == 188


class TestMovementFeeReconciliation:
    def test_movement_fee_total_excludes_cancelled_reconciles(self, api, admin_headers):
        """PRD §3.5: "`total_movement_fees_cents` sums the per-record fees over
        records in `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; cancelled records
        contribute nothing."
        PRD §3.5: "a premises' `current_head_count` equals its
        `initial_head_count` minus the summed `head_count` of every movement
        record whose chain — record to permit to certificate — leads back to
        that premises as origin, counting only records in `IN_TRANSIT` or
        `DELIVERED`. Scheduled records have not moved inventory; cancelled
        records are excluded entirely."

        Design: Corner/calculations/movement_fee_total_excludes_cancelled_reconciles
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        vet_h = make_vet_headers(scenario["vet"]["id"])
        rec1 = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=3)
        rec2 = create_scheduled_record(
            permit["id"], scenario["vet"]["id"], head_count=3,
            planned_ship_date="2026-08-22T00:00:00Z",
        )
        set_clock("2026-08-21T00:00:00Z")
        validate_success(api.depart_movement_record(rec2["id"], vet_h), 200)

        # Cancelling the SCHEDULED rec1 removes it from the fee total and both
        # headrooms; the IN_TRANSIT rec2 keeps contributing.
        validate_success(api.cancel_movement_record(rec1["id"], vet_h), 200)
        mid = get_permit(permit["id"])
        assert mid["total_movement_fees_cents"] == 413, "only IN_TRANSIT rec2 contributes"
        assert mid["committed_headroom"] == 7
        assert mid["projected_headroom"] == 7

        # Arrival keeps rec2 inside the input set: totals unchanged.
        validate_success(api.arrive_movement_record(rec2["id"], vet_h), 200)
        end = get_permit(permit["id"])
        assert end["total_movement_fees_cents"] == 413
        assert end["committed_headroom"] == 7
        assert end["projected_headroom"] == 7

        # Only the departed 3 head moved inventory; the cancelled record never did.
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 27
