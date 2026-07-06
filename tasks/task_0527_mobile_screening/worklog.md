# Worklog — task_0527_mobile_screening

## Step 1: Create task directory — 2026-07-01T00:00:00.000Z

Created `tasks/task_0527_mobile_screening/` and `workspace/` subdirectory. Using pre-specified folder (skipped auto ID scan). Expert difficulty to be passed to scaffold-generator.

## Step 3: Copy shared files — 2026-07-01T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`. (Done early; no dependency on scaffold.)

## Step 2: Generate scaffold (Expert) — 2026-07-01T00:00:00.000Z

The scaffold is complete. Final summary of what was generated.

## Summary

Generated a complete Expert-difficulty scaffold for **task_0527_mobile_screening** (Mobile Health Screening & Wellness Events) — three files, all passing `scaffold_lint.py` with `VERDICT: clean lint` (475 setup/trigger calls checked, all FK reverse-reachability satisfied).

**Files written to** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0527_mobile_screening/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** workflow_orchestration + temporal_windowing; flat topology; branching state machines; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Counts:**
- **Entities:** 10 (MobileUnit, StaffMember, Sponsor, Grant, ScreeningEvent, Participant, Appointment, Referral, Charge, Reminder)
- **State machines:** 6 (ScreeningEvent, Appointment [branching NORMAL/ABNORMAL fork], Referral, Charge [DRAFT→{ADJUDICATED,VOID}], Participant [auto ACTIVE→BLOCKED], Reminder)
- **Concurrency rules:** 2 OCC-on-Charge.version (charge-adjudicate-stale, charge-settle-stale)
- **Calculations:** 5 (patient_responsibility [provisional/finalized dual-variant], grant_depletion [estimated/actual burn], event_fill_rate [ratio-then-round], sponsor_report_totals [≥3-input nested rates], referral_priority [SLA])
- **Validations:** 15 (priority-ordered, auth→existence→state→business_safety/temporal/constraint/fiscal/referential→OCC)
- **Endpoints:** 53 (incl. `/_clock/set_current_utc` test-driving endpoint with 2026-05-01 default; all FK reverse-reachability via filtered-list GETs).
- **Error catalog:** 33 codes
- **RBAC roles:** 5 (ProgramManager, ClinicalStaff, BillingClerk, PatientNavigator, SponsorViewer)
- **Difficulty rules:** all 9 × 2 instances = **18 instances**
- **Corner cases:** 30 active instances + 1 `excluded_because` stub across 9 sections.

**Key mechanics:** 3-hop cascade (event cancel → appointment CANCELLED → charge VOID → grant.committed restored), grant conservation invariant (`total_budget == remaining + committed`), half-open minute-interval slot overlap vs. whole-day unit exclusivity, no-show strike threshold flipping participants to BLOCKED, OCC stale-version on billing charge lifecycle. Formula literals pre-computed and verified (provisional 4000 vs finalized 5000 on $200 mammogram; fill 30% / show 67%; grant depletion boundary at 0). Correction: event-close precondition allows SCHEDULED appointments (only in-progress states block closure) so no-show flow is reachable.

## Step 4: Generate PRD — 2026-07-01T00:00:00.000Z

Generated `workspace/PRD.md` — **288 lines** — for the Mobile Health Screening & Wellness Events domain (Expert difficulty band).

**Sections:** §1 Introduction (3 paragraphs), §2 Global Specifications (10 subsections: RBAC + 5 roles, fixed §2.2 envelope, pagination, common resource props/versioning, reverse-reachability + left-to-right path validation, logical clock startup `2026-05-01T00:00:00Z`, OCC on charges, grant fund conservation/depletion, monetary/percentage precision ratio-then-round, cascading side effects), §3 Business Logic (9 workflow subsections), §4 (53-endpoint table), §5 (33-error catalogue).

**Hard Contract reports:**
- Contract 1 — Field-Name Coverage: 49/49 present, 0 missing. PASS
- Contract 2 — Rule Coverage: all 33 error IDs, all 6 state machines, both OCC rules (expected_charge_version + ERR_STALE_VERSION/412), all 5 calculations (MODALITY_PRICE_CENTS 20000/8000/12000/6000, 0.20 coinsurance, DEPLETION_FLOOR zero cents, strike limit three, SLA 7/30 days), 3-hop event-cancel cascade, no-show cascade, NORMAL/ABNORMAL fork, grant conservation, validation priority ordering. PASS
- Contract 3 — §3 Path Purity: 437 tokens scanned; 0 slash-prefixed, 0 bare HTTP methods, 0 method+path. PASS

All 53 endpoints, 5 roles, every enum verbatim. Design index files not read.

## Step 6: Generate implementation — 2026-07-01T00:00:00.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`. **15 files.**

**Module layout:** `start.sh` (foreground, reads `$PORT` default 10000, binds `0.0.0.0`, guarded pip install, `exec`s app.py), `requirements.txt` (flask), `app.py` (blueprints + error handlers, threaded), `db.py` (in-memory dicts + monotonic `_seq`, empty every boot, no seeding), `clock.py` (logical UTC clock default `2026-05-01T00:00:00Z`), `response.py` (envelope + pagination meta), `errors.py` (ApiError + status catalogue), `middleware.py` (X-User-ID/X-User-Role auth + role checks), `services/` (common.py system-fields/validation/pagination/round-half-up, calc.py grant depletion/patient responsibility/referral priority-SLA/modality prices, lookup.py resource-specific 404s), `routes/` (9 blueprints: clock, roster, sponsors+grants+report, events, participants, appointments, referrals, charges, reminders).

**Endpoints implemented:** all 54.

**PRD ambiguities resolved:**
1. Grant conservation on void/cancel: recompute `committed_cents` from live charges after flipping to VOID (VOID excluded) — numerically identical to PRD subtraction, keeps invariant exact under any ordering.
2. Out-of-range pagination `limit` (0 or >100): reject with `ERR_INVALID_REQUEST` (validation priority 5). Isolated in `services/common.py::_int_query` if tests expect clamping.
3. `current_utc` format from clock endpoint: returns same 3-fractional-digit ISO-8601 UTC used everywhere.
4. Charge transition ordering: checks `ERR_INVALID_STATE` before `ERR_STALE_VERSION` on adjudicate/settle per §3.7.

## Step 5: Generate unit tests — 2026-07-01T00:00:00.000Z

Test infrastructure generation complete for `task_0527_mobile_screening`.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (13 status/role enums + entity TypedDicts), `api_client.py` (one method per PRD §4 endpoint incl. `/_clock`), `api_errors.py` (30 error IDs + HTTP-status map), `constants.py`, `factories.py`, `assertions.py` (per-entity + grant-conservation invariant), `test_users.py` (5 opaque roles; SponsorViewer per-instance builder), `fixtures.py` (composite state-progression/lifecycle/no-show-accumulation/grant-charge helpers), `__init__.py`.

**Stage 2 — `test_suite/`**: `conftest.py` + 6 domain-language test files.

**Test counts:** **62 tests total**, each carrying exactly one `Design:` tag.
- Queue A (Difficulty): 32 tests covering 16 of 18 instances, each ≥2 tests.
- Queue B (Corner): 30 tests covering all 30 non-stub instances, each ≥1 test. The 1 `excluded_because:` stub not translated.

**Instances skipped (2, left as gaps — not weakened):**
1. `Difficulty/priority_pair_validation_conflict/state_vs_temporal_overlap_on_booking` — PRD §3.4 booking-guard ordering names no event-state check / error_id for booking a non-published event; not uniquely PRD-derivable.
2. `Difficulty/transitive_cascade/event_cancel_cascade_depth3_to_grant` — PRD-inconsistent/unreachable: §3.2 cascades only SCHEDULED/CHECKED_IN appointments, but a charge exists only after screening (§3.7 → SCREENED, outside cascade set). Faithful impl leaves committed_cents at 8000, so instance's committed==0 assertion would fail correct code.

**Quality passes:** all files compile; all 78 docstring citations survive verbatim grep of PRD.md; no scaffold leakage; no skip/xfail markers.

## Step 7: Test-and-fix loop — 2026-07-01T00:00:00.000Z

All 8 rounds pass 62/62. Clean sweep. Exiting.

**Iterations run:** 2 (initial sweep + one fix + verification sweep).

**Diagnosis:** Initial 8-round sweep produced a consistent failure (all 8 rounds) in `test_third_no_show_blocks_participant`, tripping at its setup precondition: `assert participant["no_show_strikes"] == 2 ... got 0`. Deterministic, not flaky.
- STEP 1 (coverage + unique-derivability): asserts PRD §3.5 three-hop no-show cascade (strike increment; flip to BLOCKED at strike limit three; cancel PENDING reminders) — verbatim-covered and uniquely determined. Test stays.
- STEP 2 (test-vs-PRD consistency): failure was in the test_helpers/ fixture, not assertion or implementation. `create_participant_with_two_strikes()` drove two no-shows through the API correctly but returned the participant object captured at registration time (strikes still 0) instead of re-reading after the no-shows. Sibling `create_blocked_participant()` already re-reads, which is why its dependents passed. Implementation `mark-no-show` logic (routes/appointments.py) was correct all along.

**Tests deleted:** none. Every test was PRD-covered and uniquely derivable.

**Fixes applied to test_helpers/:** `fixtures.py`, `create_participant_with_two_strikes()`: added a re-read of the participant via `api_client.get_participant(...)` before returning, so the returned object reflects the two accumulated `no_show_strikes`. Makes the fixture faithful to the state the API actually holds.

**Fixes applied to implementation/:** none required — implementation was already PRD-faithful.

**Final result:** 8/8 rounds green, 62/62 tests passing each round.

## Step 8: Finalize PRD — 2026-07-01T00:00:00.000Z

**Outcome: PRD_FINALIZED.md is a verbatim copy of PRD.md — zero edits.** Line counts: PRD.md = 288, PRD_FINALIZED.md = 288. Delta 0 (0%).

**Rationale:** The sole `<step_7_diff>` item was a pure test-fixture bug (`create_participant_with_two_strikes()` returned a stale registration-time snapshot instead of re-reading after two no-shows). Fix was applied to test_helpers/fixtures.py, not implementation/. Implementation mark-no-show logic was already PRD-faithful; a fixture returning stale state is a test artifact, not PRD silence or PRD/impl mismatch → no PRD edit.

**Pre-edit search log:** subject = participant no-show-strike accumulation / auto-block / reinstate cascade. Enumerated impl paths (grep `no_show_strikes|NO_SHOW_STRIKE_LIMIT|BLOCKED|reinstate`): appointments.py:254-276 mark_no_show (3-hop cascade, matches §3.5/§3.3), participants.py:75-85 reinstate (resets strikes, matches §3.3), participants.py:37 creation (strikes 0/ACTIVE), appointments.py:40-41 blocked guard (ERR_PARTICIPANT_BLOCKED), events.py:170-196 event-cancel cascade (does NOT touch strikes, matches §3.2 carve-out), calc.py:14 NO_SHOW_STRIKE_LIMIT=3. All uniquely determined by existing PRD prose → no wording adjustment.
