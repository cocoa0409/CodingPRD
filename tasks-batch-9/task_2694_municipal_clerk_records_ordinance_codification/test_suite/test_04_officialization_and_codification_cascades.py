"""Two single calls that each propagate four hops through four different
aggregates: the tally that approves minutes, and the certificate that closes a
newspaper publication.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CITY_CLERK, CODIFICATION_EDITOR

NOISE_CURFEW = {
    "full_text_length": 1200,
    "title": "An ordinance amending the noise curfew",
}


def test_the_approving_tally_officializes_every_motion_of_the_minuted_meeting():
    """Approving the minutes of 15 September at the 6 October sitting stamps
    approved_on and flips result_official on the adoption motion nothing in the
    request ever named.

    PRD 3.4: "**Hop 2** flips `result_official` to true on *every* motion whose
    `meeting_id` is the approved minutes' `meeting_id` — not merely the adoption
    motions, and not merely the passing ones, because the whole record of that
    sitting becomes official at once."

    Design: Difficulty/transitive_cascade/minutes_approval_officializes_vote_mints_number_and_creates_notice
    """
    scenario = fx.officialized_ordinance(7, instrument_overrides=dict(NOISE_CURFEW))

    a.assert_vote_arithmetic(
        scenario["approval_motion"], effective_base=7, required_yes=4, outcome="PASSED"
    )
    a.assert_fields(
        scenario["minutes"], status="APPROVED", approved_on="2026-10-06"
    )
    adoption_motion = fx.read_motion(scenario["motion"]["id"])
    a.assert_fields(adoption_motion, result_official=True, outcome="PASSED")


def test_the_number_is_minted_off_the_series_only_when_the_vote_becomes_official():
    """The ordinance reaches ADOPTED carrying ORD-2026-001, keeps 15 September as
    its voted_on and takes 6 October as its adoption_date, while the series it was
    never named in advances.

    PRD 3.5: "When the officialization cascade of section 3.4 moves an instrument
    `ADOPTED_UNOFFICIAL → ADOPTED`, the server stamps `adoption_date` with the
    logical clock date and mints `assigned_number` by joining the series'
    `prefix`, the series' `series_year` and the series' current `next_sequence`
    zero-padded to three digits, separated by hyphens — so a series with prefix
    `ORD` for 2026 standing at sequence 7 mints `ORD-2026-007`."

    Design: Difficulty/transitive_cascade/minutes_approval_officializes_vote_mints_number_and_creates_notice
    """
    scenario = fx.officialized_ordinance(7, instrument_overrides=dict(NOISE_CURFEW))

    a.assert_fields(
        scenario["instrument"],
        status="ADOPTED",
        assigned_number="ORD-2026-001",
        adoption_date="2026-10-06",
        voted_on="2026-09-15",
    )
    a.assert_fields(scenario["number_series"], next_sequence=2, minted_count=1)


def test_adoption_raises_exactly_one_draft_full_text_notice_owing_two_insertions():
    """A 1,200-character ordinance is short enough to print entire, so hop 4
    raises an ORDINANCE_FULL_TEXT notice owing two insertions by 2026-10-21.

    PRD 3.6: "An ordinance of 4,000 characters or fewer takes
    `ORDINANCE_FULL_TEXT` and owes **two** insertions."

    Design: Difficulty/transitive_cascade/minutes_approval_officializes_vote_mints_number_and_creates_notice
    """
    scenario = fx.officialized_ordinance(7, instrument_overrides=dict(NOISE_CURFEW))

    rows, meta = validate_paginated(
        api_client.list_publication_notices(
            CITY_CLERK, {"instrument_id": scenario["instrument"]["id"]}
        )
    )

    a.assert_pagination_meta(meta, total_count=1)
    a.assert_fields(
        rows[0],
        notice_type="ORDINANCE_FULL_TEXT",
        status="DRAFT",
        required_publication_count=2,
        publication_deadline_on="2026-10-21",
    )
    a.assert_nulls(rows[0], "meeting_id", "publication_completed_on")


def test_certifying_publication_leaves_a_code_amendment_without_an_effective_date():
    """Hops 1 and 2: the notice is PUBLISHED for 17500 cents, the ordinance
    mirrors the completion date and picks SUPPLEMENT_CERTIFIED, which cannot yield
    a date until the supplement is certified.

    PRD 3.5: "Under `SUPPLEMENT_CERTIFIED` the `effective_date` is the **later**
    of that rolled date and the `certified_on` date of the supplement cycle
    carrying the instrument's accepted codification submission; while that cycle
    remains uncertified there is no date at all and `effective_date` stays null."

    Design: Difficulty/transitive_cascade/publication_certification_enrolls_codification_and_holds_a_section_conflict
    """
    scenario = fx.code_amendment_ordered_for_publication()

    certified = validate_success(
        api_client.certify_publication(
            scenario["notice"]["id"],
            f.certify_publication_payload("2026-10-14"),
            CITY_CLERK,
        )
    )

    a.assert_status(certified, "PUBLISHED")
    a.assert_cents(certified, "invoice_total_cents", 17500)
    instrument = fx.read_instrument(scenario["instrument"]["id"])
    a.assert_fields(
        instrument,
        status="PUBLISHED",
        publication_completed_on="2026-10-14",
        effective_date_basis="SUPPLEMENT_CERTIFIED",
    )
    a.assert_nulls(instrument, "effective_date")


def test_the_auto_enrolled_submission_collides_with_the_client_row_on_one_section():
    """Hops 3 and 4: the cascade files a CASCADE submission into the cycle whose
    window contains the clock date, and it lands on 12.04.030 where a different
    instrument's CLIENT row already sits, so both are held.

    PRD 3.7: "If the incoming submission collides on `code_section_ref` with a row
    of a **different** `instrument_id` whose `status` is `PENDING` or `IN_REVIEW`,
    that is a genuine old-versus-new provision conflict: **both** rows move to
    `CONFLICT_HELD`, each row's `conflict_with_submission_id` is pointed at the
    other, and the cycle's `conflict_count` advances by 1."

    Design: Difficulty/transitive_cascade/publication_certification_enrolls_codification_and_holds_a_section_conflict
    """
    scenario = fx.code_amendment_ordered_for_publication()

    validate_success(
        api_client.certify_publication(
            scenario["notice"]["id"],
            f.certify_publication_payload("2026-10-14"),
            CITY_CLERK,
        )
    )

    rows, meta = validate_paginated(
        api_client.list_codification_submissions(
            CODIFICATION_EDITOR, {"instrument_id": scenario["instrument"]["id"]}
        )
    )
    a.assert_pagination_meta(meta, total_count=1)
    cascade_row = rows[0]
    a.assert_fields(
        cascade_row,
        origin="CASCADE",
        action="AMEND",
        code_section_ref="12.04.030",
        status="CONFLICT_HELD",
    )
    client_row = fx.read_submission(scenario["client_submission"]["id"])
    a.assert_fields(client_row, origin="CLIENT", status="CONFLICT_HELD")
    assert client_row["conflict_with_submission_id"] == cascade_row["id"]
    assert cascade_row["conflict_with_submission_id"] == client_row["id"]
    a.assert_fields(
        fx.read_cycle(scenario["cycle"]["id"]),
        status="OPEN",
        submission_count=2,
        client_submission_count=1,
        conflict_count=1,
    )
