# Worklog — task_0572_ice_rink

Scenario: 572. Ice Rink & Learn-to-Skate (public skate/hockey): ice-slot scheduling & resurfacing buffer, public-skate admission & skate rental, learn-to-skate level & class, hockey/figure league & locker, rink rental & broomball, skate sharpening, party package, recurring tuition

Difficulty: Expert (passed to prd-bench-scaffold-generator only)

## Step 1: Create task directory — 2026-07-09T04:53:08.000Z

Directory `tasks/task_0572_ice_rink` was pre-allocated by the user; index scan skipped. Created `tasks/task_0572_ice_rink/workspace/`.

## Step 2: Generate scaffold (Expert) — 2026-07-09T05:31:42.000Z

All three artifacts are written and the linter reports `VERDICT: clean lint`.

Generated a fresh Expert-difficulty scaffold for the Ice Rink & Learn-to-Skate scenario:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

Complexity profile: primary archetype temporal_windowing + secondary quota_allocation; layers cascading_side_effects, dual_variant_calculation, optimistic_concurrency, derived_field_reconciliation; hybrid topology with a self-referential class-prerequisite graph edge; cyclic state machines; hierarchical_override roles; immediate consistency.

Counts:
- Entities: 12 (Rink, Skater, IceSlot, PublicSkateAdmission, LearnToSkateClass, Enrollment, TuitionSubscription, League, LeagueRegistration, LockerAssignment, SlotBooking, SharpeningOrder)
- State machines: 9
- Calculations: 7
- Validations: 12 (priority-ordered)
- Endpoints: 51
- Error codes: 12
- Roles: 3 (RinkManager/opaque, FrontDesk/opaque, Skater/entity_backed)
- Concurrency rules: 1 (OCC on Enrollment.version for supersede-on-create)
- §1.8: 9 rule_ids × 2 = 18 instances
- §1.9: 8 sections, 27 instances total (25 active + 2 excluded_because stubs)

Key findings / notes:
- All nine §0.5 Difficulty Rules are satisfied with distinct differentiators (e.g. Rule 1 dual-variant on TuitionSubscription vs SlotBooking; Rule 8 buffered ice-slot overlap on Rink vs half-open locker overlap on Locker; Rule 9 money-cents vs physical-locker-unit conservation). All formula-derived asserts were computed in code and pinned as literals (tuition 6000/4500, party 10305/8183 with per-guest-vs-aggregate rounding 8183≠8182, rental quote 36000/12000).
- `scaffold_lint.py` passes clean (251 §1.8+§1.9 calls checked; FK reverse-reachability satisfied via filtered-list GETs).
- One deviation worth flagging: endpoint count is 51, above the Expert 20–32 guideline band. This is driven by the scenario's breadth (nine sub-domains) combined with the mandatory single-GET + filtered-list-GET reverse-reachability per child collection; the skill states these are guidelines not hard rules, and difficulty is concentrated in tight cross-entity coupling rather than surface size. Entities were kept lean (12, merging rental/broomball/party into one SlotBooking and folding levels into a self-referential class) to hold the band as low as practical.
- Fixed two YAML flow-sequence issues (optional `field?` tokens and `grounds` tokens containing `[...]` needed quoting) and removed a dead `CANCELLED` enum value on SharpeningOrder that no transition produced.

## Step 3: Copy shared files — 2026-07-09T05:31:50.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0572_ice_rink/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-09T05:39:20.000Z

PRD generated at `workspace/PRD.md`.

- **Line count:** 273 lines.
- **Sections:** 5 top-level (`## 1`–`## 5`) and 16 subsections. §2 has 9 domain-derived cross-cutting subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 pagination, 2.4 logical clock, 2.5 common properties/versioning, 2.6 OCC, 2.7 wallet/money/precision, 2.8 hierarchical cascade, 2.9 nested-retrieval + priority-ordered validation ladder). §3 has 7 workflow subsections (rinks/ice-slots, admissions/rental skates, classes/enrollment/prereq, tuition/proration, leagues/registrations/lockers, private bookings, sharpening queue).

Coverage:
- **Entities (12):** All fields for Rink, Skater, IceSlot, PublicSkateAdmission, LearnToSkateClass, Enrollment, TuitionSubscription, League, LeagueRegistration, LockerAssignment, SlotBooking, SharpeningOrder covered — verified every `fields[].name` plus every endpoint `input`/`query_params` identifier (including `to_iso8601`, `current_utc`, `amount_cents`, `reason`, `expected_enrollment_version`) appears verbatim in backticks (Contract 1: 0 missing after adding `full_name`/`email`/`membership`).
- **State machines (8):** All transitions and their preconditions/side-effects expressed in prose, including the cyclic DRAFT↔SCHEDULED and ACTIVE↔PAST_DUE edges, the derived OPEN↔FULL class flips, and the three cascade chains (ice-slot cancel by purpose; enrollment-withdraw → tuition cancel; league-cancel → registration cancel → locker release). All state/enum values verified present.
- **Calculations (7):** tuition proration (CALENDAR vs SESSIONS dual variant), party charge (per-guest tax rounded then summed), rental quote (peak/off-peak tiers with member discount, broomball + resurface fees, pinned eval order), public-skate capacity, rental-skate inventory, locker availability, sharpening queue position — all translated to precise prose with constants embedded (20,000/12,000 cents-per-hour, 10% discount, 5,000/4,000 cent fees).
- **Validations (12):** Full priority-ordered ladder (1–10) stated explicitly in §2.9, each paired with its error and `applies_to` scope; OCC rule framed in stale-version terms with `expected_enrollment_version`, `ERR_STALE_VERSION`, HTTP 412.
- **Endpoints (~52):** 4-column table (Method, Path, Description, Authorized Roles); no paths/methods leak into §3 (Contract 3: PASS).
- **Errors (12):** 2-column catalogue; every error ID also surfaces in §2/§3 narrative near its trigger.
- **Roles (3):** RinkManager/FrontDesk (opaque identity) and Skater (entity-backed, `skater_id` ownership) all translated per spec.

**Hard Contracts — all PASS:** Contract 1 (field coverage, 0 missing), Contract 2 (rule coverage), Contract 3 (§3 path purity, 0 violations). Note: per instructions the subagent did not read either withheld design index file or any sibling task directory.

## Step 5: Generate Unit Tests — 2026-07-09T08:12:00.000Z

> Orchestrator note: this step was executed as a resumed run. An earlier Step 5 subagent was killed
> mid-Stage-2 by an infrastructure error (connection closed mid-response) after writing all of
> `test_helpers/` and `test_suite/test_01`–`test_02`. It was resumed from its own transcript with
> context intact rather than restarted, and instructed not to overwrite the already-written files.
> Because `workspace/implementation/` already existed on disk (Step 6 having completed before the
> original kill), the Step 5 prompt carried an additional hard read-ban on
> `workspace/implementation/**` to preserve the generation-time isolation contract. Verified
> post-hoc: no file under `test_suite/` or `test_helpers/` references `implementation`.

All fixes applied. Everything compiles, every test carries exactly one verbatim Design tag, and citations grep-confirm against PRD.md.

## Summary

Generated complete test infrastructure for `task_0572_ice_rink` under the design-index-only contract. Stage 1 (`test_helpers/`) was already on disk from the interrupted run and verified complete; I resumed Stage 2 and finished all nine test files.

**Files written**
- `test_helpers/`: `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py` (Stage 1)
- `test_suite/`: `conftest.py` + `test_01`…`test_09` (61 test functions total)

**Coverage — Queue A (Difficulty): 18/18 instances translated, 0 skipped.** Each instance has exactly 2 tests (36 tests).

**Coverage — Queue B (Corner): 25/25 non-stub instances translated (25 tests), 0 skipped.** The 2 `excluded_because:` stubs were correctly NOT translated; both cross-references resolve to real Queue-A instances:
- `state_machines/slot_cancel_learn_to_skate_cascade` → owned by `transitive_cascade/cascade_slot_cancel_class_enrollment_subscription_refund` ✓
- `validations/admission_capacity_boundary` → owned by `boundary_precision_check/public_skate_capacity_strict_boundary` ✓

**PRD-first adjudications (assertions I declined to hard-code, while still covering the instance's primary claim).** In all three the PRD pins the *delta* but not the absolute value, so a faithful PRD-only implementer could ship version-starts-at-0 or -at-1; I asserted the derivable delta instead of the literal:
- `ice_slot_draft_scheduled_cycle`: design's `version == 4` → asserted `created_version + 3` (PRD §2.5 "increments by one on every mutation"); status==SCHEDULED still asserted.
- `rink_create_returns_computed_availability`: dropped `version == 1`; kept `available_lockers == 3` / `available_rental_skates == 4` (uniquely derivable, §3.2/§3.5).
- `occ_subscription_create_bumps_enrollment_version`: design's `version == 2` → asserted the +1 delta (§3.4 "incremented by one").

**One faithful-translation adjustment (not a skip).** For `resource_temporal_overlap/ice_slot_resurface_buffer_overlap`, the design's combined setup adds a DRAFT slot B `[09:10,10:10)` that itself overlaps candidate C `[09:15,10:15)`. PRD §3.1 says DRAFT slots are non-terminal and participate in the overlap check, so a PRD-faithful server would reject C in that combined setup — contradicting the design's `slot_c == SCHEDULED`. I gave each of the two tests its own minimal setup (A+B for the collision, A+C for the buffer-boundary adjacency), preserving the instance's actual claim in a PRD-faithful way.

**Hard Contract audit — all clean**
- No file under `workspace/implementation/` was read, listed, globbed, or grepped; no server/pytest/prd-bench-local-run executed; no sibling `task_*/` inspected.
- 61 tests, each docstring ends with exactly one `Design:` line copied verbatim from the yaml `name:`; automated check confirms 1 tag/test (no untagged, dual-tagged, or dangling tags).
- Distinctive ≥8-word PRD citations spot-checked via literal `grep` of `PRD.md` (11 clauses confirmed; the one initial miss was a dropped backtick, since fixed).
- `python3 -m py_compile` passes on all `test_suite/` and `test_helpers/` files.

## Step 6: Generate Implementation — (completed in the interrupted run, before Step 5)

> Orchestrator note: `workspace/implementation/` (`app.py` 1575 lines, `start.sh`, `requirements.txt`)
> was generated by the original run at a point when `test_suite/` did not yet exist, so the
> impl-generator's physical isolation from the tests held. Per the resume instructions this artifact
> was preserved and NOT regenerated. No subagent summary is available for this step — the original
> subagent's context was discarded when the run was killed. Verified present and
> `python3 -m py_compile app.py` passes.

## Step 7: Run Tests and Iterate — 2026-07-09T15:10:00.000Z

> Orchestrator note: this step was executed as a resumed run after the previous orchestrator was
> killed by system memory pressure. The prior run had already completed one 8-round parallel sweep
> (8/8 rounds agreeing at 59/61, two deterministic failures). That observation was passed to the
> Step 7 subagent as baseline context only; the subagent was still required to run its own fresh
> sweep and re-read its own `results.*.json` per STEP 0 before diagnosing.
>
> Post-hoc verification by the orchestrator: all 8 `results.{1..8}.json` report `passed=59 total=59
> failed=0`; `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` returns no
> hits; 59 test functions and 59 `Design:` tags remain (1:1 preserved after the 2 deletions).
> The deletion rationale was independently spot-checked against `workspace/PRD.md` §3.5 (lines
> 176–182): the league-registration payload is enumerated as `skater_id` + optional `locker_number`
> / `season_start_date` / `season_end_date`, a league carries no `rink_id`, and the endpoint is
> `POST /leagues/{id}/registrations` — so the rink binding for the side-effect locker assignment is
> indeed not PRD-derivable. Deletion under STEP 1b confirmed correct.

All 8 parallel rounds are clean (59/59 each). Exiting with the summary.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps.
- Sweep 1 (baseline verification): 59/61 passing, deterministic across all 8 rounds. Union of failures = `test_league_cancel_cascades_to_registration_and_locker`, `test_league_cancel_restores_available_lockers`. Both failed identically in every round during **setup** with `HTTP 400 ERR_INVALID_REQUEST - rink_id required to reserve a locker`.
- Sweep 2 (post-fix): 59/59 passing in all 8 rounds.

**Tests deleted (2)** — both in `test_suite/test_05_leagues_and_lockers.py`:
- `test_league_cancel_cascades_to_registration_and_locker`
- `test_league_cancel_restores_available_lockers`

Deletion category: **STEP 1b unique-derivability collapse — feature under-specification (no PRD-derivable rink binding).** Scaffold rule that drove their generation: `Difficulty/transitive_cascade/cascade_league_cancel_registration_locker_release` (SCAFFOLD_DIFFICULTY_DESIGN.yaml:374).

Rationale: Both tests depend on a setup precondition — a league registration that reserves a locker at a *specific* rink — that the PRD cannot uniquely determine. PRD line 178 lists the registration-with-locker payload as exactly `skater_id`, `locker_number`, `season_start_date`, `season_end_date` (no rink); PRD line 176 gives a league no `rink_id` field; and the endpoint path is `POST /leagues/{id}/registrations` (names the league, not a rink). A faithful PRD-only implementer therefore has no way to know which rink to charge or whose `available_lockers` to decrement — the two-reader experiment diverges: (A) invent an undocumented `rink_id` body field (what the implementation did, hence the setup 400), vs. (B) no faithful rink binding at all. Adding `rink_id` to the fixture was rejected because it would inject a field the PRD does not declare, contradicting line 178's explicit field enumeration and making the test *less* faithful. The cascade/`available_lockers` assertions themselves are PRD-covered, but they are unreachable without the non-derivable setup, so the whole tests go.

**Fixes to `test_helpers/`:** none (the `setup_league_registration_with_locker` fixture and `register_skater`'s locker path in `fixtures.py` are now unused but left in place; the only now-unused import `setup_league_registration_with_locker` was removed from the test module).

**Fixes to `implementation/`:** none. The implementation's `rink_id`-required behavior in `create_registration` (app.py:1248-1252) is itself not PRD-traceable, but the correct PRD-First resolution was to delete the non-derivable tests, not to add or weaken implementation logic.

Relevant files:
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0572_ice_rink/test_suite/test_05_leagues_and_lockers.py` (2 tests + 1 import removed)
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0572_ice_rink/workspace/PRD.md` (lines 176, 178, 180, 182; endpoint table 244)
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0572_ice_rink/workspace/implementation/app.py` (create_registration, lines 1222-1286)

Test count: 61 → 59, all passing deterministically across 8 concurrent rounds.

## Step 8: Finalize PRD — align documentation to implementation — 2026-07-09T15:22:00.000Z

> Orchestrator note: the Step 8 skip condition (0 deletions AND 0 `test_suite/` fixes AND 0
> `test_helpers/` fixes AND 0 `implementation/` fixes) did NOT apply — Step 7 recorded 2 deletions
> and 1 `test_suite/` import removal — so Step 8 ran. The Step 7 worklog entry above was inlined
> verbatim as `<step_7_diff>`. Post-hoc verification: `diff PRD.md PRD_FINALIZED.md` shows exactly
> one changed line (178), an inline revision, no new sections.

Done. PRD_FINALIZED.md is written with a minimal patch pinning the one PRD silence revealed by the Step 7 diff.

## Summary

**Line counts:** PRD.md = 273 lines, PRD_FINALIZED.md = 273 lines (0% line delta — both edits are inline within existing line 178). Word count 6267 → 6320 (+53 words, +0.85%).

**Changes (both in §3.5, Leagues/Registrations/Lockers):**
- §3.5 — revise — added `rink_id` (naming the rink that owns the locker) to the optional locker-reservation field list on `POST /leagues/{id}/registrations` — impl `app.py:1235,1278`
- §3.5 — revise — stated that when a `locker_number` is supplied, a `rink_id` is mandatory (omitting it → `ERR_INVALID_REQUEST`), the locker side effect is created at that named rink, and that rink's locker fee is charged / its available lockers decremented; noted `rink_id` is request-only and not persisted on the registration — impl `app.py:1250-1252, 1274-1284`

**Why this is the one edit:** The Step 7 diff deleted two league-cancel cascade tests because their setup (a registration reserving a locker at a *specific* rink) was not PRD-derivable — PRD line 178 enumerated the registration payload without any `rink_id`, and a league carries no rink. Step 7 aligned tests to PRD (deletion). Step 8 aligns PRD to implementation: the impl requires `rink_id` in the registration body to reserve a locker (`create_registration`, app.py:1248-1252), so a fresh implementer needs that field documented to reproduce the behavior (including the 400 when `locker_number` is present but `rink_id` is absent).

**Per-edit pre-edit search log:**

Edit 1 & 2 (single subject: the `rink_id` body field on the registration locker side effect)
- (a) Subject: the `rink_id` input on `POST /leagues/{id}/registrations` and how the locker side effect binds/prices to a rink.
- (b) Impl paths enumerated and read:
  - `create_registration` app.py:1222-1286 — accepts optional body `rink_id`; requires it when `locker_number` present (400 otherwise, line 1251-1252); creates locker at that rink, charges `rink["locker_fee_cents"]`, decrements that rink's `available_lockers` (lines 1274-1284).
  - `create_locker` (direct endpoint) app.py:1323-1362 — parallel path where `rink_id` comes from the URL path, `league_registration_id=None`; confirmed my wording is scoped to the *registration* path and does not contradict the direct path.
  - `cascade_league_cancel` app.py:561-569 — releases lockers by `league_registration_id`; unaffected by the wording.
  - `ser_registration` app.py:350-354 — does NOT serialize `rink_id` (only `league_id`, `skater_id`, `status`); this drove the added clause "request-only input … not persisted on the registration resource" so I don't falsely imply `rink_id` is a registration field.
  - `available_lockers` derivation app.py:238-240 (per-rink, counts distinct ACTIVE locker_numbers) — confirmed "reducing that rink's available lockers" is accurate.
- (c) Wording adjustment: scoped fee/availability language to "that rink" (the named rink) rather than an ambiguous "the rink"; added the explicit "request-only, not persisted" clause to stay consistent with `ser_registration`; left the endpoint-table row (line 241) generic and unchanged since it already reads "optionally reserve a locker."

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-07-09T15:31:00.000Z

> Orchestrator note: Step 9 always runs (no skip condition). Source was `PRD_FINALIZED.md` (present
> from Step 8). Post-hoc verification: all three PRDs are 273 lines; `diff PRD_FINALIZED.md
> PRD_COMPLETED.md` touches 8 lines, all in-paragraph; `diff` of the heading sets is empty (no new
> sections); `implementation/app.py` mtime (14:13) predates both Step 8 (14:58) and Step 9 (15:04),
> confirming the alignment target was never mutated by the documentation steps.

Done. I walked `implementation/app.py` exhaustively against `PRD_FINALIZED.md` and pinned every point where the PRD left a behavior open or under-specified relative to what the code actually does. All changes are in-paragraph inserts/revisions; no new sections or paragraphs.

## Summary

- Source `PRD_FINALIZED.md`: 273 lines, 43,963 chars
- `PRD_COMPLETED.md`: 273 lines, 45,076 chars (char delta +1,113; line count unchanged — all inline)
- Ambiguity-pins: 10; Mismatch-revisions: 0 (implementation exhibited no behavior that directly contradicted PRD prose; every gap was silence)

## Changes

- §2.1 (RBAC) — insert — ambiguity — Skater ownership is enforced only on by-`id` reads/mutations; list endpoints are NOT ownership-filtered, so a Skater listing a collection gets all matching rows — `app.py:893-902,1012-1021,1106-1115,1298-1307,1374-1383,1457-1466,1547-1556` (no `check_owner` in any `list_*`)
- §2.3 (Pagination) — insert — ambiguity — a negative `offset` is rejected with `ERR_INVALID_REQUEST` — `app.py:457-458`
- §2.7 (Wallet/registration) — insert — ambiguity — a duplicate skater `email` is rejected with `ERR_INVALID_REQUEST` — `app.py:691-693`
- §3.1 (Rinks) — insert — ambiguity — `open_hour_utc`, `close_hour_utc`, and `peak_start_hour_utc` must each be 0–23, else `ERR_INVALID_REQUEST` (PRD only bounded `open_hour_utc`) — `app.py:655-660`
- §3.1 (Ice-slot publish) — insert — ambiguity — the operating-hours guard failure on publish returns `ERR_INVALID_STATE` (error was unnamed in PRD) — `app.py:779-780`
- §3.3 (Classes) — insert — ambiguity — creating a class on a non-`LEARN_TO_SKATE` slot is rejected with `ERR_INVALID_STATE` — `app.py:937-938`
- §3.4 (Advance cycle) — insert — ambiguity — advance requires `ACTIVE` status (else `ERR_INVALID_STATE`) and `billing_cycle_end` is treated as midnight UTC of that date — `app.py:1123-1128`
- §3.4 (Advance cycle) — insert — ambiguity — the one-month roll clamps the day to the target month's last valid day when the original day doesn't exist there — `app.py:515-523`
- §3.6 (Booking completion) — insert — ambiguity — party `guest_count_final` for completion is read from the complete request body, falling back to the value stored on the booking — `app.py:1480-1483`
- §3.6 (Booking completion) — insert — ambiguity — the completion top-up delta is applied unconditionally with no insufficient-funds guard, so a positive difference may drive the wallet negative — `app.py:1486-1492`

Notable behaviors that were already pinned uniquely by the PRD and required no change: rental/party/proration formulas, cascade chains, validation-ordering (§2.9), OCC on subscription create, queue-position recomputation, admission/refund revenue-vs-refund distinction, and locker overlap/index rules.
