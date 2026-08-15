"""Re-enrollment offers: sibling-discount lines, OCC on the student version,
supersede, and response deadlines (PRD §3.7, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_reenrollment_offer_payload,
    get_offer,
    get_student,
    make_parent_headers,
    make_reenrollment_offer,
    respond_offer,
    run_sweep,
    set_clock,
    setup_reenrollment_world,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiblingDiscountPerLine:
    """Difficulty: each additional-sibling discount is rounded per line BEFORE
    summation; the pinned order is observable in the family total."""

    def _three_sibling_world(self):
        return setup_reenrollment_world(
            current_grades=(("G9", 3_000_000), ("G5", 2_800_000),
                            ("G3", 2_600_000)),
            target_grades=(("G10", 3_200_000), ("G6", 2_833_333),
                           ("G4", 2_833_333)),
            students=(("fam-r", 0), ("fam-r", 1), ("fam-r", 2)),
        )

    def test_per_line_discounts_rounded_before_summation(self, api,
                                                         director_headers):
        """PRD §3.7: "The family's senior student — index zero — receives a
        `sibling_discount_cents` of zero; each additional sibling's line
        receives ten percent of that line's `new_tuition_cents`, rounded
        half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/reenrollment_sibling_discount_per_line_rounding
        """
        world = self._three_sibling_world()
        target_id = world["target_cycle"]["id"]
        st1, st2, st3 = world["students"]
        of1 = make_reenrollment_offer(st1["id"], target_id)
        of2 = make_reenrollment_offer(st2["id"], target_id)
        of3 = make_reenrollment_offer(st3["id"], target_id)
        # Senior line: no discount.
        assert of1["prior_tuition_cents"] == 3_000_000
        assert of1["new_tuition_cents"] == 3_200_000
        assert of1["sibling_discount_cents"] == 0
        assert of1["discounted_tuition_cents"] == 3_200_000
        # Additional siblings: round_half_up(0.10 * 2,833,333) = 283,333 each.
        assert of2["new_tuition_cents"] == 2_833_333
        assert of2["sibling_discount_cents"] == 283_333
        assert of2["discounted_tuition_cents"] == 2_550_000
        assert of3["sibling_discount_cents"] == 283_333
        assert of3["discounted_tuition_cents"] == 2_550_000

    def test_family_total_is_sum_of_per_line_rounded_values(
            self, api, director_headers):
        """PRD §3.7: "Each line's `discounted_tuition_cents` is then its
        `new_tuition_cents` minus its `sibling_discount_cents`, and the
        family's total for the target cycle is the sum of the per-line
        discounted values. The rounding order is pinned: each line's discount
        is rounded to whole cents first, and only then are the lines summed —
        summing raw tuitions and rounding a single ten percent of the
        aggregate afterwards produces different cents and is not the rule."

        Design: Difficulty/combinatorial_formula/reenrollment_sibling_discount_per_line_rounding
        """
        world = self._three_sibling_world()
        target_id = world["target_cycle"]["id"]
        for student in world["students"]:
            make_reenrollment_offer(student["id"], target_id)
        data, meta = validate_paginated(
            api.list_reenrollment_offers(
                director_headers,
                params={"family_id": "fam-r", "cycle_id": target_id},
            )
        )
        assert meta["total_count"] == 3
        family_total = sum(row["discounted_tuition_cents"] for row in data)
        # 3,200,000 + 2,550,000 + 2,550,000; rounding 10% of the aggregate
        # instead would yield 8,299,999 — the pinned order is observable.
        assert family_total == 8_300_000


class TestOfferIssuanceOcc:
    def test_occ_reenrollment_stale_version_rejected(self, api,
                                                     director_headers):
        """PRD §2.8: "If the supplied value does not match the student's
        current `version`, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and nothing is written."
        PRD §3.7: "Issuing a new offer supersedes any prior `ISSUED` offer for
        the same student and cycle, moving the older one to `SUPERSEDED`, and
        increments the student's `version` by one — which is precisely what
        makes a stale `expected_student_version` detectable."

        Design: Corner/complexity_layers/occ_reenrollment_stale_version_rejected
        """
        world = setup_reenrollment_world()
        student = world["students"][0]
        target_id = world["target_cycle"]["id"]
        stale_version = student["version"]
        first = validate_success(
            api.create_reenrollment_offer(
                create_reenrollment_offer_payload(student["id"], target_id,
                                                  stale_version),
                director_headers,
            ),
            201,
        )
        # The create itself bumped the student's version by one.
        assert get_student(student["id"])["version"] == stale_version + 1
        # A second create on the stale view is the lost-update case.
        resp = api.create_reenrollment_offer(
            create_reenrollment_offer_payload(student["id"], target_id,
                                              stale_version),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        # On a fresh view the create is legal and supersedes the first offer.
        fresh_version = get_student(student["id"])["version"]
        second = validate_success(
            api.create_reenrollment_offer(
                create_reenrollment_offer_payload(student["id"], target_id,
                                                  fresh_version),
                director_headers,
            ),
            201,
        )
        assert get_offer(first["id"])["status"] == "SUPERSEDED"
        assert get_offer(second["id"])["status"] == "ISSUED"


class TestOfferIssuanceConstraints:
    def test_reenroll_no_next_grade_rejected(self, api, director_headers):
        """PRD §3.7: "Issuance requires a grade section for the student's next
        grade to exist in the target cycle — the natural progression from the
        student's current grade, with `G12` students graduating and therefore
        having no next grade — or it fails with `ERR_NO_NEXT_GRADE`."

        Design: Corner/validations/reenroll_no_next_grade_rejected
        """
        world = setup_reenrollment_world(current_grades=(("G12", 3_200_000),),
                                         target_grades=())
        student = world["students"][0]
        resp = api.create_reenrollment_offer(
            create_reenrollment_offer_payload(
                student["id"], world["target_cycle"]["id"], student["version"],
            ),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_NEXT_GRADE, 409)

    def test_reenroll_already_accepted_rejected(self, api, director_headers):
        """PRD §3.7: "And once a family has accepted, the matter is settled:
        creating any further offer for the same student and cycle while an
        `ACCEPTED` offer exists is `ERR_REENROLL_ALREADY_ACCEPTED`."
        PRD §3.7: "An acceptance moves the offer `ISSUED` → `ACCEPTED` and
        records the commitment on the student by setting
        `re_enrolled_for_cycle_id` to the offer's `cycle_id`".

        Design: Corner/validations/reenroll_already_accepted_rejected
        """
        world = setup_reenrollment_world()
        student = world["students"][0]
        target_id = world["target_cycle"]["id"]
        offer = make_reenrollment_offer(student["id"], target_id)
        set_clock("2027-02-01T00:00:00Z")  # inside the response window
        respond_offer(offer["id"], "fam-r", "ACCEPTED")
        # The constraint fires even with a fresh OCC version.
        fresh_version = get_student(student["id"])["version"]
        resp = api.create_reenrollment_offer(
            create_reenrollment_offer_payload(student["id"], target_id,
                                              fresh_version),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REENROLL_ALREADY_ACCEPTED, 409)
        assert get_offer(offer["id"])["status"] == "ACCEPTED"
        assert get_student(student["id"])["re_enrolled_for_cycle_id"] == \
            target_id


class TestOfferResponseWindow:
    def test_respond_lapsed_reenrollment_rejected(self, api, director_headers):
        """PRD §3.7: "Offers the family ignores are lapsed by the operational
        sweep on the target cycle once the clock passes `response_deadline_at`,
        moving them `ISSUED` → `LAPSED`."
        PRD §3.7: "Responding requires the offer to be `ISSUED`
        (`ERR_REENROLL_NOT_ISSUED` otherwise)".

        Design: Corner/state_machines/respond_lapsed_reenrollment_rejected
        """
        world = setup_reenrollment_world()
        offer = make_reenrollment_offer(world["students"][0]["id"],
                                        world["target_cycle"]["id"])
        set_clock("2027-03-02T00:00:00Z")  # past response deadline 2027-03-01
        sweep = run_sweep(world["target_cycle"]["id"])
        assert sweep["lapsed_reenrollment_count"] == 1
        assert get_offer(offer["id"])["status"] == "LAPSED"
        resp = api.respond_reenrollment_offer(
            offer["id"], "ACCEPTED", make_parent_headers("fam-r"),
        )
        validate_error(resp, ApiErrorId.ERR_REENROLL_NOT_ISSUED, 409)

    def test_respond_after_deadline_belt_rejected(self, api):
        """PRD §3.7: "Responding requires the offer to be `ISSUED`
        (`ERR_REENROLL_NOT_ISSUED` otherwise) and the logical clock to be at
        or before `response_deadline_at` — a belt check surfacing
        `ERR_REENROLL_WINDOW_CLOSED` even before a sweep would lapse the
        offer."

        Design: Corner/validations/respond_after_deadline_belt_rejected
        """
        world = setup_reenrollment_world()
        offer = make_reenrollment_offer(world["students"][0]["id"],
                                        world["target_cycle"]["id"])
        set_clock("2027-03-02T00:00:00Z")  # past the deadline; NO sweep run
        resp = api.respond_reenrollment_offer(
            offer["id"], "ACCEPTED", make_parent_headers("fam-r"),
        )
        validate_error(resp, ApiErrorId.ERR_REENROLL_WINDOW_CLOSED, 422)
        assert get_offer(offer["id"])["status"] == "ISSUED"
