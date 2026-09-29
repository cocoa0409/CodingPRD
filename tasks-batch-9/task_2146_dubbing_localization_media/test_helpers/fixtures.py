"""Composite setup helpers.

Almost every interesting claim in this contract needs the system parked at a
precise point of the localization pipeline, and reaching that point takes
between five and forty-three API calls. `setup_canon(n)` walks the canonical
pipeline and stops after step `n`, so a test can name the exact state it needs:

     1  logical clock moved to the scenario instant
     2  title                                    ->  t_id
     3  root cut (loop_count 400)                ->  c_id, c_v1
     4  cut locked
     5  character HERO                           ->  ch1_id
     6  character SIDEKICK                       ->  ch2_id
     7  platform specification                   ->  ps_id
     8  studio "Booth 1"                         ->  st_id
     9  voice talent Anna Vogel                  ->  tal1_id
    10  voice talent Bruno Keller                ->  tal2_id
    11  localization order (EXPEDITED, DE)       ->  o_id          [DRAFT]
    12  script adaptation opened                 ->  sa_id         [SCRIPT_IN_PROGRESS]
    13  translate
    14  adapt (declared_loop_count 380)
    15  submit-review (22800 / 38)                              [order -> CASTING]
    16  review APPROVE
    17  read order version                       ->  o_v1
    18  casting assignment 1 (HERO / Anna)       ->  ca1_id
    19  request-hold ca1
    20  respond-hold ca1 ACCEPT
    21  confirm ca1                                             [ca1 CONFIRMED]
    22  read order version                       ->  o_v2
    23  casting assignment 2 (SIDEKICK / Bruno)  ->  ca2_id
    24  request-hold ca2
    25  respond-hold ca2 ACCEPT
    26  confirm ca2
    27  session 1  09:00-11:00 on ca1            ->  s1_id       [order -> RECORDING]
    28  session 2  12:00-13:08 on ca2            ->  s2_id
    29  confirm session 1
    30  confirm session 2
    31  clock -> 2026-09-10T09:00Z
    32  start session 1
    33  complete session 1                                      [ca1 RECORDED]
    34  clock -> 2026-09-10T12:00Z
    35  start session 2
    36  complete session 2                                      [ca2 RECORDED]
    37  talent payment on ca1                    ->  tp1_id      [ca1 ACCRUED]
    38  mix job                                  ->  mj_id
    39  stem-check
    40  mix (-24.8 LUFS)                                        [order -> MIXING]
    41  conform                                                 [order -> QC]
    42  quality review                           ->  qr_id
    43  start review round (200 loops)                          [review IN_REVIEW]

Every step uses the lenient setup validator so a broken precondition reports
"Setup step failed" rather than an obscure KeyError.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ADAPTOR_1, REVIEWER_1, REVIEWER_2, TEST_DEFAULTS
from .factories import (
    adapt_payload,
    create_casting_assignment_payload,
    create_character_payload,
    create_cut_payload,
    create_localization_order_payload,
    create_mix_job_payload,
    create_platform_spec_payload,
    create_quality_review_payload,
    create_recording_session_payload,
    create_script_adaptation_payload,
    create_studio_payload,
    create_talent_payment_payload,
    create_title_payload,
    create_voice_talent_payload,
    decide_fail_payload,
    defect_entry,
    mix_payload,
    review_adaptation_payload,
    start_review_payload,
    submit_review_payload,
)
from .test_users import (
    make_adaptor_headers,
    make_native_reviewer_headers,
    make_voice_talent_headers,
    ADMIN,
    CASTING,
    MIXER,
    PC,
)


# --------------------------------------------------------------------------
# Small building blocks
# --------------------------------------------------------------------------
def set_clock(iso_instant: str) -> dict:
    """Move the server's logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso_instant}, ADMIN))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_localization_order(order_id, PC))


def order_version(order_id: str) -> int:
    return read_order(order_id)["version"]


def create_title(ctx: dict, key: str = "t_id", **overrides) -> dict:
    row = get_success_data(api_client.create_title(create_title_payload(**overrides), PC))
    ctx[key] = row["id"]
    return row


def create_cut(ctx: dict, key: str = "c_id", title_key: str = "t_id", **overrides) -> dict:
    row = get_success_data(
        api_client.create_cut(create_cut_payload(ctx[title_key], **overrides), PC)
    )
    ctx[key] = row["id"]
    ctx[key.replace("_id", "_v1")] = row["version"]
    return row


def derive_cut(ctx: dict, parent_key: str, key: str, parent_version: int, **overrides) -> dict:
    payload = {
        "cut_code": overrides.pop("cut_code", "AIRLINE"),
        "loop_count": overrides.pop("loop_count", 360),
        "runtime_seconds": overrides.pop("runtime_seconds", 6900),
        "expected_parent_cut_version": parent_version,
    }
    payload.update(overrides)
    row = get_success_data(api_client.derive_cut(ctx[parent_key], payload, PC))
    ctx[key] = row["id"]
    return row


def create_character(ctx: dict, key: str, title_key: str = "t_id", **overrides) -> dict:
    row = get_success_data(
        api_client.create_character(create_character_payload(ctx[title_key], **overrides), PC)
    )
    ctx[key] = row["id"]
    return row


def create_platform_spec(ctx: dict, key: str = "ps_id", **overrides) -> dict:
    row = get_success_data(
        api_client.create_platform_spec(create_platform_spec_payload(**overrides), PC)
    )
    ctx[key] = row["id"]
    return row


def create_studio(ctx: dict, key: str = "st_id", **overrides) -> dict:
    row = get_success_data(api_client.create_studio(create_studio_payload(**overrides), PC))
    ctx[key] = row["id"]
    return row


def create_voice_talent(ctx: dict, key: str, **overrides) -> dict:
    row = get_success_data(
        api_client.create_voice_talent(create_voice_talent_payload(**overrides), CASTING)
    )
    ctx[key] = row["id"]
    return row


def create_order(ctx: dict, key: str = "o_id", cut_key: str = "c_id",
                 spec_key: str = "ps_id", **overrides) -> dict:
    row = get_success_data(
        api_client.create_localization_order(
            create_localization_order_payload(ctx[cut_key], ctx[spec_key], **overrides), PC
        )
    )
    ctx[key] = row["id"]
    return row


def open_script_workstream(ctx: dict, order_key: str = "o_id", key: str = "sa_id",
                           adaptor_user: str = ADAPTOR_1) -> dict:
    headers = make_adaptor_headers(adaptor_user)
    row = get_success_data(
        api_client.create_script_adaptation(
            create_script_adaptation_payload(ctx[order_key]), headers
        )
    )
    ctx[key] = row["id"]
    return row


def walk_script_to_in_review(ctx: dict, key: str = "sa_id", adaptor_user: str = ADAPTOR_1,
                             declared_loop_count=None, measured=None, over=None) -> dict:
    """translate -> adapt -> submit-review. Leaves the adaptation IN_REVIEW."""
    headers = make_adaptor_headers(adaptor_user)
    adaptation_id = ctx[key]
    get_success_data(api_client.translate_adaptation(adaptation_id, headers))
    adapt_kwargs = {}
    if declared_loop_count is not None:
        adapt_kwargs["declared_loop_count"] = declared_loop_count
    get_success_data(
        api_client.adapt_adaptation(adaptation_id, adapt_payload(**adapt_kwargs), headers)
    )
    submit_kwargs = {}
    if measured is not None:
        submit_kwargs["measured_sync_deviation_ms_total"] = measured
    if over is not None:
        submit_kwargs["lines_over_deviation"] = over
    return get_success_data(
        api_client.submit_adaptation_review(
            adaptation_id, submit_review_payload(**submit_kwargs), headers
        )
    )


def approve_script(ctx: dict, key: str = "sa_id", reviewer_user: str = REVIEWER_1) -> dict:
    return get_success_data(
        api_client.review_adaptation(
            ctx[key], review_adaptation_payload("APPROVE"),
            make_native_reviewer_headers(reviewer_user),
        )
    )


def cast_and_confirm(ctx: dict, key: str, character_key: str, talent_key: str,
                     version_key: str, **overrides) -> dict:
    """Create an assignment then walk PROPOSED -> HOLD_REQUESTED -> HELD -> CONFIRMED."""
    ctx[version_key] = order_version(ctx["o_id"])
    row = get_success_data(
        api_client.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o_id"], ctx[character_key], ctx[talent_key], ctx[version_key], **overrides
            ),
            CASTING,
        )
    )
    ctx[key] = row["id"]
    talent_headers = make_voice_talent_headers(ctx[talent_key])
    get_success_data(api_client.request_hold(row["id"], CASTING))
    get_success_data(api_client.respond_hold(row["id"], {"response": "ACCEPT"}, talent_headers))
    return get_success_data(api_client.confirm_casting_assignment(row["id"], CASTING))


def book_session(ctx: dict, key: str, assignment_key: str, start_utc: str, end_utc: str,
                 studio_key: str = "st_id", order_key: str = "o_id", **overrides) -> dict:
    row = get_success_data(
        api_client.create_recording_session(
            create_recording_session_payload(
                ctx[order_key], ctx[studio_key], ctx[assignment_key], start_utc, end_utc,
                **overrides
            ),
            PC,
        )
    )
    ctx[key] = row["id"]
    return row


def run_session_to_completed(ctx: dict, session_key: str, clock_instant: str) -> dict:
    """confirm (when still SCHEDULED) -> move clock -> start -> complete."""
    session_id = ctx[session_key]
    current = get_success_data(api_client.get_recording_session(session_id, PC))
    if current["status"] == "SCHEDULED":
        get_success_data(api_client.confirm_recording_session(session_id, PC))
    set_clock(clock_instant)
    get_success_data(api_client.start_recording_session(session_id, PC))
    return get_success_data(api_client.complete_recording_session(session_id, PC))


def accrue_payment(ctx: dict, key: str, assignment_key: str, territory_scope=None) -> dict:
    scope = territory_scope if territory_scope is not None else ["US", "DE", "JP"]
    row = get_success_data(
        api_client.create_talent_payment(
            create_talent_payment_payload(ctx[assignment_key], scope), ADMIN
        )
    )
    ctx[key] = row["id"]
    return row


def open_and_conform_mix(ctx: dict, key: str = "mj_id", loudness_lufs=None, **overrides) -> dict:
    """Create a mix job and walk QUEUED -> STEM_CHECKED -> MIXED -> CONFORMED."""
    row = get_success_data(
        api_client.create_mix_job(create_mix_job_payload(ctx["o_id"], **overrides), MIXER)
    )
    ctx[key] = row["id"]
    get_success_data(api_client.stem_check_mix_job(row["id"], MIXER))
    kwargs = {} if loudness_lufs is None else {"loudness_lufs": loudness_lufs}
    get_success_data(api_client.mix_mix_job(row["id"], mix_payload(**kwargs), MIXER))
    return get_success_data(api_client.conform_mix_job(row["id"], MIXER))


def open_quality_review(ctx: dict, key: str = "qr_id", reviewer_user: str = REVIEWER_2) -> dict:
    row = get_success_data(
        api_client.create_quality_review(
            create_quality_review_payload(ctx["o_id"], ctx["mj_id"]),
            make_native_reviewer_headers(reviewer_user),
        )
    )
    ctx[key] = row["id"]
    return row


def start_review_round(ctx: dict, key: str = "qr_id", reviewer_user: str = REVIEWER_2,
                       sampled_loop_count=None) -> dict:
    kwargs = {} if sampled_loop_count is None else {"sampled_loop_count": sampled_loop_count}
    return get_success_data(
        api_client.start_quality_review(
            ctx[key], start_review_payload(**kwargs),
            make_native_reviewer_headers(reviewer_user),
        )
    )


def fail_review_round(ctx: dict, assignment_key: str = "ca1_id", key: str = "qr_id",
                      reviewer_user: str = REVIEWER_2, loop_ref: str = "L-0042",
                      defect_category: str = "LIPSYNC", defect_count: int = 30) -> dict:
    """Decide FAIL with one defect entry, firing the four-link regression cascade."""
    defects = [defect_entry(ctx[assignment_key], loop_ref, defect_category)]
    return get_success_data(
        api_client.decide_quality_review(
            ctx[key], decide_fail_payload(defects, defect_count=defect_count),
            make_native_reviewer_headers(reviewer_user),
        )
    )


def first_retake_item_id(ctx: dict, key: str = "qr_id", reviewer_user: str = REVIEWER_2) -> str:
    rows = get_success_data(
        api_client.list_retake_items(
            make_native_reviewer_headers(reviewer_user), {"quality_review_id": ctx[key]}
        )
    )
    assert rows, "Setup step failed: the QC failure raised no retake item"
    return rows[0]["id"]


# --------------------------------------------------------------------------
# The canonical pipeline
# --------------------------------------------------------------------------
def setup_canon(n: int = 43, **opts) -> dict:
    """Walk the canonical pipeline and stop after step `n` (see the module docstring).

    Recognised overrides:
      clock, title, cut, character1, character2, spec, studio, talent1, talent2,
      order, ca1, ca2, session1, session2, mix, payment_scope,
      loudness_lufs, sampled_loop_count, declared_loop_count, measured,
      lines_over_deviation, adaptor_user, script_reviewer_user, qc_reviewer_user
    """
    ctx: dict = {}
    d = TEST_DEFAULTS

    if n < 1:
        return ctx
    set_clock(opts.get("clock", d["CLOCK_SETUP"]))

    if n < 2:
        return ctx
    create_title(ctx, **(opts.get("title") or {}))

    if n < 3:
        return ctx
    create_cut(ctx, **(opts.get("cut") or {}))

    if n < 4:
        return ctx
    get_success_data(api_client.lock_cut(ctx["c_id"], PC))

    if n < 5:
        return ctx
    create_character(
        ctx, "ch1_id",
        **(opts.get("character1") or {"character_code": "HERO", "loop_count": 220,
                                      "screen_time_seconds": 3000, "is_principal": True}),
    )

    if n < 6:
        return ctx
    create_character(
        ctx, "ch2_id",
        **(opts.get("character2") or {"character_code": "SIDEKICK", "loop_count": 180,
                                      "screen_time_seconds": 1500, "is_principal": False}),
    )

    if n < 7:
        return ctx
    create_platform_spec(ctx, **(opts.get("spec") or {}))

    if n < 8:
        return ctx
    create_studio(ctx, **(opts.get("studio") or {}))

    if n < 9:
        return ctx
    create_voice_talent(ctx, "tal1_id", **(opts.get("talent1") or {"full_name": "Anna Vogel"}))

    if n < 10:
        return ctx
    create_voice_talent(
        ctx, "tal2_id",
        **(opts.get("talent2") or {"full_name": "Bruno Keller"}),
    )

    if n < 11:
        return ctx
    create_order(ctx, **(opts.get("order") or {}))

    adaptor_user = opts.get("adaptor_user", ADAPTOR_1)
    if n < 12:
        return ctx
    open_script_workstream(ctx, adaptor_user=adaptor_user)

    if n < 13:
        return ctx
    get_success_data(
        api_client.translate_adaptation(ctx["sa_id"], make_adaptor_headers(adaptor_user))
    )

    if n < 14:
        return ctx
    adapt_kwargs = {}
    if "declared_loop_count" in opts:
        adapt_kwargs["declared_loop_count"] = opts["declared_loop_count"]
    get_success_data(
        api_client.adapt_adaptation(
            ctx["sa_id"], adapt_payload(**adapt_kwargs), make_adaptor_headers(adaptor_user)
        )
    )

    if n < 15:
        return ctx
    submit_kwargs = {}
    if "measured" in opts:
        submit_kwargs["measured_sync_deviation_ms_total"] = opts["measured"]
    if "lines_over_deviation" in opts:
        submit_kwargs["lines_over_deviation"] = opts["lines_over_deviation"]
    get_success_data(
        api_client.submit_adaptation_review(
            ctx["sa_id"], submit_review_payload(**submit_kwargs),
            make_adaptor_headers(adaptor_user),
        )
    )

    if n < 16:
        return ctx
    approve_script(ctx, reviewer_user=opts.get("script_reviewer_user", REVIEWER_1))

    if n < 17:
        return ctx
    ctx["o_v1"] = order_version(ctx["o_id"])

    if n < 18:
        return ctx
    ca1_overrides = dict(opts.get("ca1") or {})
    ca1_overrides.setdefault("usage_variant", "BUYOUT")
    ca1_overrides.setdefault("agreed_rate_cents_per_hour", d["CA1_RATE_CENTS_PER_HOUR"])
    ca1 = get_success_data(
        api_client.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o_id"], ctx["ch1_id"], ctx["tal1_id"], ctx["o_v1"], **ca1_overrides
            ),
            CASTING,
        )
    )
    ctx["ca1_id"] = ca1["id"]

    if n < 19:
        return ctx
    get_success_data(api_client.request_hold(ctx["ca1_id"], CASTING))

    if n < 20:
        return ctx
    get_success_data(
        api_client.respond_hold(
            ctx["ca1_id"], {"response": "ACCEPT"}, make_voice_talent_headers(ctx["tal1_id"])
        )
    )

    if n < 21:
        return ctx
    get_success_data(api_client.confirm_casting_assignment(ctx["ca1_id"], CASTING))

    if n < 22:
        return ctx
    ctx["o_v2"] = order_version(ctx["o_id"])

    if n < 23:
        return ctx
    ca2_overrides = dict(opts.get("ca2") or {})
    ca2_overrides.setdefault("usage_variant", "RESIDUAL")
    ca2_overrides.setdefault("agreed_rate_cents_per_hour", d["CA2_RATE_CENTS_PER_HOUR"])
    ca2 = get_success_data(
        api_client.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o_id"], ctx["ch2_id"], ctx["tal2_id"], ctx["o_v2"], **ca2_overrides
            ),
            CASTING,
        )
    )
    ctx["ca2_id"] = ca2["id"]

    if n < 24:
        return ctx
    get_success_data(api_client.request_hold(ctx["ca2_id"], CASTING))

    if n < 25:
        return ctx
    get_success_data(
        api_client.respond_hold(
            ctx["ca2_id"], {"response": "ACCEPT"}, make_voice_talent_headers(ctx["tal2_id"])
        )
    )

    if n < 26:
        return ctx
    get_success_data(api_client.confirm_casting_assignment(ctx["ca2_id"], CASTING))

    if n < 27:
        return ctx
    s1 = dict(opts.get("session1") or {})
    book_session(
        ctx, "s1_id", "ca1_id",
        s1.pop("start_utc", d["SESSION_1_START"]),
        s1.pop("end_utc", d["SESSION_1_END"]),
        **s1,
    )

    if n < 28:
        return ctx
    s2 = dict(opts.get("session2") or {})
    book_session(
        ctx, "s2_id", "ca2_id",
        s2.pop("start_utc", d["SESSION_2_START"]),
        s2.pop("end_utc", d["SESSION_2_END"]),
        **s2,
    )

    if n < 29:
        return ctx
    get_success_data(api_client.confirm_recording_session(ctx["s1_id"], PC))

    if n < 30:
        return ctx
    get_success_data(api_client.confirm_recording_session(ctx["s2_id"], PC))

    if n < 31:
        return ctx
    set_clock("2026-09-10T09:00:00Z")

    if n < 32:
        return ctx
    get_success_data(api_client.start_recording_session(ctx["s1_id"], PC))

    if n < 33:
        return ctx
    get_success_data(api_client.complete_recording_session(ctx["s1_id"], PC))

    if n < 34:
        return ctx
    set_clock("2026-09-10T12:00:00Z")

    if n < 35:
        return ctx
    get_success_data(api_client.start_recording_session(ctx["s2_id"], PC))

    if n < 36:
        return ctx
    get_success_data(api_client.complete_recording_session(ctx["s2_id"], PC))

    if n < 37:
        return ctx
    accrue_payment(ctx, "tp1_id", "ca1_id", opts.get("payment_scope"))

    if n < 38:
        return ctx
    mj = get_success_data(
        api_client.create_mix_job(
            create_mix_job_payload(ctx["o_id"], **(opts.get("mix") or {})), MIXER
        )
    )
    ctx["mj_id"] = mj["id"]

    if n < 39:
        return ctx
    get_success_data(api_client.stem_check_mix_job(ctx["mj_id"], MIXER))

    if n < 40:
        return ctx
    loud = {} if opts.get("loudness_lufs") is None else {"loudness_lufs": opts["loudness_lufs"]}
    get_success_data(api_client.mix_mix_job(ctx["mj_id"], mix_payload(**loud), MIXER))

    if n < 41:
        return ctx
    get_success_data(api_client.conform_mix_job(ctx["mj_id"], MIXER))

    qc_reviewer = opts.get("qc_reviewer_user", REVIEWER_2)
    if n < 42:
        return ctx
    open_quality_review(ctx, reviewer_user=qc_reviewer)

    if n < 43:
        return ctx
    start_review_round(
        ctx, reviewer_user=qc_reviewer,
        sampled_loop_count=opts.get("sampled_loop_count"),
    )
    return ctx


# --------------------------------------------------------------------------
# Named shortcuts over the canonical pipeline
# --------------------------------------------------------------------------
def setup_locked_cut_and_spec(**spec_overrides) -> dict:
    """Locked root cut plus one platform specification, nothing else."""
    ctx = setup_canon(4)
    create_platform_spec(ctx, **spec_overrides)
    return ctx


def setup_draft_order(spec_overrides=None, **order_overrides) -> dict:
    """A brand-new order sitting in DRAFT."""
    ctx = setup_locked_cut_and_spec(**(spec_overrides or {}))
    create_order(ctx, **order_overrides)
    return ctx


def setup_order_in_casting(**opts) -> dict:
    """Order in CASTING with an APPROVED adaptation and ca1 CONFIRMED."""
    return setup_canon(21, **opts)


def setup_both_cast_confirmed(**opts) -> dict:
    """Order in CASTING with both assignments CONFIRMED and no sessions yet."""
    return setup_canon(26, **opts)


def setup_both_sessions_completed(**opts) -> dict:
    """Order in RECORDING with both sessions COMPLETED and both assignments RECORDED."""
    return setup_canon(36, **opts)


def setup_order_in_qc(**opts) -> dict:
    """Order in QC: mix CONFORMED, review PENDING. No talent payment accrued."""
    ctx = setup_canon(36, **opts)
    open_and_conform_mix(ctx, loudness_lufs=opts.get("loudness_lufs"))
    open_quality_review(ctx, reviewer_user=opts.get("qc_reviewer_user", REVIEWER_2))
    return ctx


def setup_review_in_progress(**opts) -> dict:
    """Order in QC with an accrued payment on ca1 and the review round started."""
    return setup_canon(43, **opts)


def setup_delivered_order(**opts) -> dict:
    """Full pipeline through the QC PASS and the delivery."""
    ctx = setup_canon(43, **opts)
    get_success_data(
        api_client.decide_quality_review(
            ctx["qr_id"], {"decision": "PASS", "defect_count": 20},
            make_native_reviewer_headers(opts.get("qc_reviewer_user", REVIEWER_2)),
        )
    )
    get_success_data(
        api_client.deliver_order(
            ctx["o_id"],
            {"metadata_locale_fields": {"title_local": "Der Titel",
                                        "synopsis_local": "Die Inhaltsangabe"}},
            PC,
        )
    )
    return ctx


def setup_after_qc_failure(**opts) -> dict:
    """Order pushed back to RECORDING by a failed QC round, with one OPEN retake item."""
    ctx = setup_canon(43, **opts)
    fail_review_round(ctx)
    ctx["ri_id"] = first_retake_item_id(ctx)
    return ctx


def setup_open_retake_with_order_back_in_qc(**opts) -> dict:
    """A failed QC round whose retake item is still `OPEN`, with the order returned to `QC`.

    The re-entry start action requires the owning order to be in `QC` on both paths,
    so a test of the open-retake refusal must first walk the order back there. That
    walk uses a *non*-retake session on the regressed assignment: only a session whose
    `is_retake` is true closes an `OPEN` retake item, so booking a plain session
    re-advances the assignment to `RECORDED` — which the mix print requires — while
    leaving the retake item open.
    """
    ctx = setup_canon(43, **opts)
    fail_review_round(ctx)
    ctx["ri_id"] = first_retake_item_id(ctx)

    # ca1 regressed RECORDED -> CONFIRMED; re-record it without touching the retake item.
    book_session(ctx, "s3_id", "ca1_id", "2026-09-10T14:00:00Z", "2026-09-10T16:00:00Z")
    run_session_to_completed(ctx, "s3_id", "2026-09-10T14:00:00Z")

    # The failing round regressed the mix job to STEM_CHECKED; print and conform it
    # again to cascade the order RECORDING -> MIXING -> QC.
    loud = {} if opts.get("loudness_lufs") is None else {"loudness_lufs": opts["loudness_lufs"]}
    get_success_data(api_client.mix_mix_job(ctx["mj_id"], mix_payload(**loud), MIXER))
    get_success_data(api_client.conform_mix_job(ctx["mj_id"], MIXER))
    return ctx
