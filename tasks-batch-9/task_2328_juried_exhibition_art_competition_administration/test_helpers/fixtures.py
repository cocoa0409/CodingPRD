"""Composite setup helpers.

Every helper builds its preconditions from scratch through the documented
endpoints, because each test starts against an empty database. Setup calls use
the lenient `get_success_data` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion.

Ownership-gated calls always thread the acting entity's own id into the header
builder (`make_artist_headers`, `make_juror_headers`); the shared header
constants are never used where an ownership check runs.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_artist_payload,
    create_artwork_image_payload,
    create_artwork_payload,
    create_assignment_payload,
    create_award_payload,
    create_condition_report_payload,
    create_conflict_declaration_payload,
    create_entry_payload,
    create_exhibition_payload,
    create_installation_plan_payload,
    create_jury_round_payload,
    create_juror_payload,
    create_sale_payload,
    create_score_payload,
    create_sponsor_payload,
    create_wall_segment_payload,
    unique_suffix,
)
from .test_users import (
    CALL_MANAGER,
    FINANCE_A,
    FINANCE_B,
    JURY_CHAIR_A,
    JURY_CHAIR_B,
    REGISTRAR,
    make_artist_headers,
    make_juror_headers,
)

# ─── Reference work descriptions ──────────────────────

WORK_RIDGE_LINE = {
    "title": "Ridge Line",
    "medium_category": "PAINTING",
    "width_cm": 90.0,
    "height_cm": 60.0,
    "depth_cm": 4.0,
    "weight_kg": 6.0,
    "declared_value_cents": 400000,
    "for_sale": True,
    "list_price_cents": 250000,
}

WORK_SALT_FLAT = {
    "title": "Salt Flat",
    "medium_category": "PHOTOGRAPHY",
    "width_cm": 100.0,
    "height_cm": 70.0,
    "depth_cm": 4.0,
    "weight_kg": 5.0,
    "declared_value_cents": 300000,
    "for_sale": True,
    "list_price_cents": 250000,
}

ALL_CANONICAL_MEDIA = ["PAINTING", "PHOTOGRAPHY", "SCULPTURE"]

# Instants the canonical calendar is walked through.
CLOCK_CALL_OPEN = "2026-09-02T00:00:00Z"
CLOCK_CALL_CLOSED = "2026-10-02T00:00:00Z"
CLOCK_SCORING = "2026-10-06T10:00:00Z"
CLOCK_DELIVERY = "2026-11-03T09:00:00Z"
CLOCK_OPENING = "2026-11-12T18:00:00Z"
CLOCK_CLOSING = "2026-12-13T00:00:00Z"


# ─── Clock and exhibition ─────────────────────────────

def set_clock(to_iso8601: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or CALL_MANAGER)
    )


def create_exhibition(**overrides) -> dict:
    return get_success_data(
        api_client.create_exhibition(create_exhibition_payload(**overrides), CALL_MANAGER)
    )


def read_exhibition(exhibition_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_exhibition(exhibition_id, headers or CALL_MANAGER)
    )


def exhibition_version(exhibition_id: str) -> int:
    return read_exhibition(exhibition_id)["version"]


def advance_phase(exhibition_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.advance_exhibition_phase(
            exhibition_id, {"target_status": target_status}, CALL_MANAGER
        )
    )


def open_call(clock: str = CLOCK_CALL_OPEN, **exhibition_overrides) -> dict:
    """Create an exhibition and carry it `DRAFT → OPEN_FOR_ENTRIES`."""
    set_clock(clock)
    exhibition = create_exhibition(**exhibition_overrides)
    return advance_phase(exhibition["id"], "OPEN_FOR_ENTRIES")


# ─── Artists, entries and works ───────────────────────

def register_artist(**overrides) -> dict:
    payload = create_artist_payload(**overrides)
    if "email" not in overrides:
        payload["email"] = f"artist{unique_suffix()}@example.org"
    return get_success_data(api_client.create_artist(payload, CALL_MANAGER))


def read_artist(artist_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_artist(artist_id, headers or CALL_MANAGER)
    )


def open_entry(exhibition_id: str, artist: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_entry(
            create_entry_payload(exhibition_id, artist["id"], **overrides),
            make_artist_headers(artist["id"]),
        )
    )


def attach_work(entry_id: str, artist: dict, with_primary_image: bool = True,
                capture_date: str = "2026-08-15T00:00:00Z", **artwork_overrides) -> dict:
    headers = make_artist_headers(artist["id"])
    artwork = get_success_data(
        api_client.attach_artwork(
            entry_id, create_artwork_payload(**artwork_overrides), headers
        )
    )
    if with_primary_image:
        upload_primary_image(artwork["id"], artist, capture_date=capture_date)
    return artwork


def upload_primary_image(artwork_id: str, artist: dict, **overrides) -> dict:
    return get_success_data(
        api_client.upload_artwork_image(
            artwork_id,
            create_artwork_image_payload(**overrides),
            make_artist_headers(artist["id"]),
        )
    )


def setup_entry_with_works(exhibition_id: str, artist: dict, works=None) -> tuple:
    """Open a `DRAFT` entry and attach each work with one `PRIMARY` image."""
    works = list(works) if works is not None else [WORK_RIDGE_LINE, WORK_SALT_FLAT]
    entry = open_entry(exhibition_id, artist)
    artworks = [attach_work(entry["id"], artist, **work) for work in works]
    return entry, artworks


def submit_entry(entry_id: str, artist: dict) -> dict:
    return get_success_data(
        api_client.submit_entry(entry_id, make_artist_headers(artist["id"]))
    )


def pay_entry_fee(entry_id: str, artist: dict, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_entry_fee(
            entry_id, {"amount_cents": amount_cents}, make_artist_headers(artist["id"])
        )
    )


def setup_submitted_entry(exhibition_id: str, artist: dict, works=None) -> tuple:
    """Open, populate, submit and pay an entry so it reaches `SUBMITTED`.

    The tendered amount is the fee the server froze at submission, so the
    fixture never presumes a fee figure of its own.
    """
    entry, artworks = setup_entry_with_works(exhibition_id, artist, works)
    submitted = submit_entry(entry["id"], artist)
    paid = pay_entry_fee(entry["id"], artist, submitted["entry_fee_cents"])
    return paid, artworks


# ─── Read-backs ───────────────────────────────────────

def read_entry(entry_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_entry(entry_id, headers or CALL_MANAGER))


def read_artwork(artwork_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_artwork(artwork_id, headers or CALL_MANAGER))


def read_juror(juror_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_juror(juror_id, headers or JURY_CHAIR_A))


def read_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_juror_assignment(assignment_id, headers or JURY_CHAIR_A)
    )


def read_sponsor(sponsor_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sponsor(sponsor_id, headers or CALL_MANAGER))


def read_award(award_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_award(award_id, headers or JURY_CHAIR_A))


def read_sale(sale_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sale(sale_id, headers or FINANCE_A))


# ─── Jury ─────────────────────────────────────────────

def enter_jurying(exhibition_id: str, clock: str = CLOCK_CALL_CLOSED) -> dict:
    set_clock(clock)
    return advance_phase(exhibition_id, "JURYING")


def invite_juror(**overrides) -> dict:
    payload = create_juror_payload(**overrides)
    if "email" not in overrides:
        payload["email"] = f"juror{unique_suffix()}@example.org"
    return get_success_data(api_client.create_juror(payload, JURY_CHAIR_A))


def confirm_juror(juror: dict) -> dict:
    return get_success_data(
        api_client.confirm_juror(juror["id"], make_juror_headers(juror["id"]))
    )


def invite_and_confirm_juror(**overrides) -> dict:
    juror = invite_juror(**overrides)
    confirm_juror(juror)
    return juror


def create_jury_round(exhibition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_jury_round(
            create_jury_round_payload(exhibition_id, **overrides), JURY_CHAIR_A
        )
    )


def read_jury_round(jury_round_id: str) -> dict:
    return get_success_data(api_client.get_jury_round(jury_round_id, JURY_CHAIR_A))


def book_session(jury_round_id: str, juror: dict,
                 session_start_at: str = "2026-10-06T09:00:00Z",
                 session_end_at: str = "2026-10-06T13:00:00Z") -> dict:
    version = read_jury_round(jury_round_id)["version"]
    return get_success_data(
        api_client.create_juror_assignment(
            jury_round_id,
            create_assignment_payload(
                juror["id"], version,
                session_start_at=session_start_at,
                session_end_at=session_end_at,
            ),
            JURY_CHAIR_A,
        )
    )


def set_round_status(jury_round_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.set_jury_round_status(
            jury_round_id, {"target_status": target_status}, JURY_CHAIR_A
        )
    )


def submit_score(jury_round_id: str, juror: dict, artwork_id: str,
                 technique: int = 7, originality: int = 8,
                 relevance: int = 9) -> dict:
    return get_success_data(
        api_client.submit_score(
            jury_round_id,
            create_score_payload(artwork_id, technique, originality, relevance),
            make_juror_headers(juror["id"]),
        )
    )


def file_conflict_declaration(juror: dict, artist: dict,
                              relation_type: str = "TEACHER_STUDENT") -> dict:
    return get_success_data(
        api_client.file_conflict_declaration(
            juror["id"],
            create_conflict_declaration_payload(artist["id"], relation_type),
            make_juror_headers(juror["id"]),
        )
    )


def setup_open_round(exhibition_id: str, juror: dict = None,
                     round_overrides: dict = None,
                     scoring_clock: str = CLOCK_SCORING) -> tuple:
    """Advance to `JURYING`, confirm a juror, create a round, book a session and
    open the round. Leaves the clock inside the scoring window."""
    enter_jurying(exhibition_id)
    if juror is None:
        juror = invite_and_confirm_juror(
            expertise_categories=list(ALL_CANONICAL_MEDIA)
        )
    jury_round = create_jury_round(exhibition_id, **(round_overrides or {}))
    book_session(jury_round["id"], juror)
    jury_round = set_round_status(jury_round["id"], "OPEN")
    set_clock(scoring_clock)
    return jury_round, juror


def run_acceptance_list(exhibition_id: str, headers=None) -> dict:
    version = exhibition_version(exhibition_id)
    return get_success_data(
        api_client.run_acceptance_list(
            exhibition_id, {"expected_exhibition_version": version},
            headers or JURY_CHAIR_A,
        )
    )


def promote_artwork(artwork_id: str, exhibition_id: str) -> dict:
    version = exhibition_version(exhibition_id)
    return get_success_data(
        api_client.promote_artwork(
            artwork_id, {"expected_exhibition_version": version}, JURY_CHAIR_A
        )
    )


# ─── Gallery, delivery and installation ───────────────

def register_wall(exhibition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_wall_segment(
            create_wall_segment_payload(exhibition_id, **overrides), REGISTRAR
        )
    )


def read_wall(wall_segment_id: str) -> dict:
    return get_success_data(api_client.get_wall_segment(wall_segment_id, REGISTRAR))


def enter_installation(exhibition_id: str, clock: str = CLOCK_DELIVERY) -> dict:
    set_clock(clock)
    return advance_phase(exhibition_id, "INSTALLATION")


def file_condition_report(artwork_id: str, stage: str = "INTAKE",
                          condition_grade: str = "A", **overrides) -> dict:
    return get_success_data(
        api_client.file_condition_report(
            artwork_id,
            create_condition_report_payload(stage, condition_grade, **overrides),
            REGISTRAR,
        )
    )


def plan_span(artwork_id: str, wall: dict, span_start_cm: float,
              span_end_cm: float) -> dict:
    version = read_wall(wall["id"])["version"]
    return get_success_data(
        api_client.file_installation_plan(
            artwork_id,
            create_installation_plan_payload(
                wall["id"], span_start_cm, span_end_cm, version
            ),
            REGISTRAR,
        )
    )


def install_artwork(artwork_id: str) -> dict:
    return get_success_data(api_client.install_artwork(artwork_id, REGISTRAR))


def deinstall_artwork(artwork_id: str, condition_grade: str = "A",
                      photo_count: int = 2) -> dict:
    """File the deinstall condition report the operation requires, then take the
    work off the wall."""
    file_condition_report(
        artwork_id, "DEINSTALL", condition_grade, photo_count=photo_count
    )
    return get_success_data(api_client.deinstall_artwork(artwork_id, REGISTRAR))


def hang_artworks(artwork_ids, wall: dict, first_start: float = 0.0,
                  pitch: float = 200.0) -> None:
    """Intake, plan and install each work at well-separated spans."""
    for index, artwork_id in enumerate(artwork_ids):
        file_condition_report(artwork_id, "INTAKE", "A")
        start = first_start + index * pitch
        plan_span(artwork_id, wall, start, start + 100.0)
        install_artwork(artwork_id)


def go_on_view(exhibition_id: str, clock: str = CLOCK_OPENING) -> dict:
    set_clock(clock)
    return advance_phase(exhibition_id, "ON_VIEW")


def close_show(exhibition_id: str, clock: str = CLOCK_CLOSING) -> dict:
    set_clock(clock)
    return advance_phase(exhibition_id, "CLOSED")


# ─── Sponsors, awards and sales ───────────────────────

def register_sponsor(exhibition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsor(
            create_sponsor_payload(exhibition_id, **overrides), CALL_MANAGER
        )
    )


def propose_award(exhibition_id: str, artwork_id: str,
                  category: str = "BEST_IN_SHOW", prize_cents: int = 100000,
                  headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_award(
            create_award_payload(
                exhibition_id, artwork_id, category, prize_cents, **overrides
            ),
            headers or JURY_CHAIR_A,
        )
    )


def confirm_award(award_id: str, exhibition_id: str, headers=None) -> dict:
    version = exhibition_version(exhibition_id)
    return get_success_data(
        api_client.confirm_award(
            award_id, {"expected_exhibition_version": version},
            headers or JURY_CHAIR_B,
        )
    )


def record_sale(artwork_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_sale(
            create_sale_payload(artwork_id, **overrides), headers or FINANCE_A
        )
    )


def invoice_and_pay_sale(sale: dict, headers=None) -> dict:
    officer = headers or FINANCE_A
    get_success_data(api_client.invoice_sale(sale["id"], officer))
    return get_success_data(
        api_client.record_sale_payment(
            sale["id"], {"amount_cents": sale["buyer_total_cents"]}, officer
        )
    )


def setup_paid_sale(artwork_id: str, recorder=None, **overrides) -> dict:
    """Record, invoice and pay a gallery sale so it reaches `PAID`."""
    sale = record_sale(artwork_id, headers=recorder or FINANCE_A, **overrides)
    return invoice_and_pay_sale(sale, headers=recorder or FINANCE_A)


def advance_settlement(exhibition_id: str, target: str, headers=None) -> dict:
    return get_success_data(
        api_client.advance_settlement(
            exhibition_id, {"target_settlement_status": target},
            headers or FINANCE_B,
        )
    )


def release_payout(sale_id: str, exhibition_id: str, headers=None) -> dict:
    version = exhibition_version(exhibition_id)
    return get_success_data(
        api_client.release_sale_payout(
            sale_id, {"expected_exhibition_version": version}, headers or FINANCE_B
        )
    )


def arrange_return(artwork_id: str, return_method: str = "ARTIST_PICKUP",
                   **overrides) -> dict:
    payload = {"return_method": return_method}
    payload.update(overrides)
    return get_success_data(
        api_client.arrange_return_shipment(artwork_id, payload, REGISTRAR)
    )


def run_unclaimed_sweep(exhibition_id: str) -> dict:
    return get_success_data(
        api_client.run_unclaimed_sweep(exhibition_id, REGISTRAR)
    )


# ─── Whole-show pipelines ─────────────────────────────

def setup_shortlisted_show(works=None, exhibition_overrides=None,
                           artist_overrides=None, scores=None,
                           juror_overrides=None, round_overrides=None) -> dict:
    """Carry a call all the way to a completed, closed round number 1.

    `scores` is a list of `(technique, originality, relevance)` tuples, one per
    work, defaulting to a card that clears the canonical advance threshold.
    Returns a context dict with every entity the caller may need.
    """
    works = list(works) if works is not None else [WORK_RIDGE_LINE]
    exhibition = open_call(**(exhibition_overrides or {}))
    artist = register_artist(**(artist_overrides or {}))
    entry, artworks = setup_submitted_entry(exhibition["id"], artist, works)

    juror_kwargs = {"expertise_categories": list(ALL_CANONICAL_MEDIA)}
    juror_kwargs.update(juror_overrides or {})
    juror = invite_and_confirm_juror(**juror_kwargs)
    jury_round, juror = setup_open_round(
        exhibition["id"], juror=juror, round_overrides=round_overrides
    )

    cards = scores if scores is not None else [(7, 8, 9)] * len(artworks)
    for artwork, card in zip(artworks, cards):
        submit_score(jury_round["id"], juror, artwork["id"], *card)

    set_round_status(jury_round["id"], "SCORING_COMPLETE")
    set_round_status(jury_round["id"], "CLOSED")

    return {
        "exhibition": exhibition,
        "artist": artist,
        "artist_headers": make_artist_headers(artist["id"]),
        "entry": entry,
        "artworks": artworks,
        "juror": juror,
        "juror_headers": make_juror_headers(juror["id"]),
        "jury_round": jury_round,
    }


def setup_results_published_show(wall_overrides=None, **kwargs) -> dict:
    """Extend `setup_shortlisted_show` with a registered wall and the
    acceptance-list run that publishes results."""
    ctx = setup_shortlisted_show(**kwargs)
    ctx["wall"] = register_wall(ctx["exhibition"]["id"], **(wall_overrides or {}))
    ctx["acceptance_result"] = run_acceptance_list(ctx["exhibition"]["id"])
    return ctx


def setup_installation_show(wall_overrides=None, **kwargs) -> dict:
    """Extend `setup_results_published_show` into the `INSTALLATION` phase."""
    ctx = setup_results_published_show(wall_overrides=wall_overrides, **kwargs)
    enter_installation(ctx["exhibition"]["id"])
    return ctx


def setup_on_view_show(wall_overrides=None, **kwargs) -> dict:
    """Extend `setup_installation_show` through intake, hanging and `ON_VIEW`.

    Every accepted work is condition-reported, planned onto the wall at
    well-separated spans, installed, and carried on view.
    """
    ctx = setup_installation_show(wall_overrides=wall_overrides, **kwargs)
    accepted_ids = ctx["acceptance_result"]["accepted_artwork_ids"]
    hang_artworks(accepted_ids, ctx["wall"])
    go_on_view(ctx["exhibition"]["id"])
    ctx["accepted_artwork_ids"] = accepted_ids
    return ctx


def setup_sold_show(sale_overrides=None, **kwargs) -> dict:
    """An on-view show with its first accepted work sold and paid for."""
    ctx = setup_on_view_show(**kwargs)
    artwork_id = ctx["accepted_artwork_ids"][0]
    ctx["sale"] = setup_paid_sale(artwork_id, **(sale_overrides or {}))
    ctx["sold_artwork_id"] = artwork_id
    return ctx
