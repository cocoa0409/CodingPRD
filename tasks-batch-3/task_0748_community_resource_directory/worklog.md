# Worklog: task_0748_community_resource_directory

## Step 1: Create task directory — 2026-07-04T17:00:00.000Z

Created `tasks/task_0748_community_resource_directory/` with `workspace/` subdirectory (pre-assigned per user).

## Step 2: Generate scaffold — 2026-07-04T18:30:00.000Z

result: Generated three scaffold files at Expert difficulty for task_0748 Community Resource & Social-Services Directory; `scaffold_lint.py` reports **VERDICT: clean lint** across 416 scanned calls.

**Files written (absolute paths):**
- `/home/ubuntu/github/CodingPRD/tasks/task_0748_community_resource_directory/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0748_community_resource_directory/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0748_community_resource_directory/SCAFFOLD_CORNER_DESIGN.yaml`

**Key counts:**
- 11 entities · 38 endpoints · 6 state machines · 6 calculations · 32 validations · 32 errors · 5 roles · 1 concurrency rule (OCC on Program)
- §1.8: 18 active difficulty instances (9 rules × 2 each)
- §1.9: 27 active corner instances + 2 excluded_because stubs, spread across 7 sections

**Notable design decisions:**
- Primary archetype: **workflow_orchestration** (referral pipeline PROPOSED→ACCEPTED→SERVICE_IN_PROGRESS→COMPLETED_*) with **quota_allocation** secondary (Program capacity slots).
- **Peer-roles** RBAC with 3 entity_backed roles (ProviderStaff→Provider, Client→Client, FunderReporter→Funder) plus 2 opaque roles (PlatformAdmin, Caseworker).
- **Parallel state dimensions** on Program: `intake_posture` (OPEN/RESTRICTED/CLOSED, capacity-driven) and `funder_reporting_posture` (OPEN/LOCKED/ARCHIVED, funder-report-driven) evolve independently — satisfies Rule 3.
- **Cyclic Intake** DRAFT↔SCREENED via reopen endpoint — second non-linear machine.
- **Branching ConsentGrant** GRANTED→{REVOKED cascades WITHDRAWN; EXPIRED does NOT cascade} — divergent side-effect sets.
- **Dual-variant calculations** across different entity domains: (a) service_cost_estimate PROVISIONAL@Referral vs FINAL@OutcomeReport, (b) funder_report_allocation PER_REFERRAL_ROUND_THEN_SUM vs SUM_THEN_ROUND (satisfies Rule 1 AND supplies Rule 2 mode (b) nested rounding — with worked example of 1503 vs 1502).
- **eligibility_score** designed with 6 inputs, nested tier branches, urgency multiplier; threshold pinned at 75.0 with an inclusive-boundary test at exactly 75.00 (Rule 2 mode (a) + Rule 6).
- **Half-open vs closed-closed interval semantics** intentionally differ: AvailabilityWindow uses `[start,end)` (Rule 8 instance 1); TransportPlan uses `[start,end]` with a 30-minute buffer between plans on the same client (Rule 8 instance 2).
- **Compensating invariants** on two distinct conserved quantities: Funder.grant_cents_remaining (money) via outcome-report reverse; Program.capacity_slots_taken (integer slot count) via referral withdraw.
- **Depth-3 cascade** from consent-revoke: ConsentGrant→Referral→TransportPlan (Rule 4 instance 1); second cascade from complete: Referral→Program.capacity_slots_taken→Program.intake_posture (Rule 4 instance 2), different trigger.
- Added a `/_clock/set_current_utc` test-driving endpoint with mandated default `2026-03-01T00:00:00Z`; added `GET /intakes/{id}`, `GET /consent-grants/{id}`, `GET /referrals/{id}` after §1.5 audit revealed lint needed them to derive collection segments for FK reverse-reachability.

## Step 3: Copy INSTRUCTION.md — 2026-07-04T18:31:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T18:36:00.000Z

result: PRD.md written at /home/ubuntu/github/CodingPRD/tasks/task_0748_community_resource_directory/workspace/PRD.md — 280 lines; §1 intro, §2.1–2.10 global specs (verbatim §2.2, plus 8 domain-derived cross-cutting subsections covering RBAC, pagination, common properties, nested-path validation, OCC, program's two independent postures, financial/precision/ledger, temporal semantics, validation priority ordering), §3.1–3.8 business workflows (directory setup, client onboarding & intake revision cycle, consent lifecycle with revoke-vs-expiry sibling branches, referral creation with full eligibility scoring formula and travel-burden dual variants, referral lifecycle, transport plans with 30-minute buffer, outcomes with grant ledger and compensating reversal, funder reporting with both rounding variants and fiscal-year archival), §4 endpoint table (37 rows, 4 columns), §5 error catalogue (32 rows, 2 columns). Contract 1 (Field-Name Coverage): 69 required, 69 present, 0 missing. Contract 2 (Rule Coverage): all high-risk categories expressed — OCC rule names `expected_program_version`+`ERR_STALE_PROGRAM_VERSION`+HTTP 412; all cascade side effects (`capacity_slots_taken` decrement, `intake_posture` recomputation, intake bubble-up-to-`CLOSED`, `TransportPlan` `SCHEDULED → CANCELLED`); all calculation formulas expressed in precise business prose with no pseudocode/fuzzy words (eligibility score with income tiers 0.50/0.80/1.00, weights 0.30/0.20/0.25/0.15/0.10, urgency multipliers 1.00/1.20/1.50, threshold 75.0; travel burden with speeds 25.0/40.0/5.0/20.0 KPH, winding 1.35, DEG_TO_KM 111.0; service cost with 0.50 base and 0.10 hours coefficient; grant ledger invariant; funder-report rounding-variant divergence); validation priority explicitly ordered in §2.10 and §3.4. Contract 3 (§3 Path Purity): 457 §3 backticked tokens scanned, 0 slash-prefixed, 0 bare-method, 0 method+path — all endpoint references use state-transition framing or role+action-verb rewrite modes. Notable design decisions: chose 10 §2 subsections (§2.1–2.10) organized by cross-cutting concern with two-dimension posture semantics as its own subsection (§2.7) since intake_posture and funder_reporting_posture evolve independently; chose 8 §3 subsections by business-lifecycle timeline (build → onboard → consent → refer → serve → transport → outcome → report); called out `FunderReport`'s `common_fields: false` (no `updated_at`/`version`) explicitly in both §2.4 and §3.8 per skill spec; kept §4 endpoint description column deliberately terse so §3 narrative remains the authoritative source. No ambiguities in the scaffold required interpretation; SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not read per the hard constraint.

## Step 5: Generate unit tests — 2026-07-04T18:51:00.000Z

result: Generated test_helpers/ (1261 LOC across 9 files) and test_suite/ (1455 LOC across 3 files) for task_0748_community_resource_directory; 36 tests from queue A cover all 18 Difficulty instances at 2 tests each, 27 tests from queue B cover all 27 non-stub Corner instances at 1 test each, both excluded Corner stubs cross-reference to real Difficulty instances (nothing skipped).

**Files created:**

test_helpers/ (Stage 1):
- `test_helpers/__init__.py` (97 LOC) — barrel export
- `test_helpers/types.py` (278 LOC) — 8 status enums, 5 domain enums, 11 entity TypedDicts (FunderReport omits `updated_at`/`version` per common_fields:false)
- `test_helpers/api_client.py` (139 LOC) — ApiClient with one method per endpoint (43 total)
- `test_helpers/api_errors.py` (77 LOC) — 32-entry ApiErrorId enum + HTTP status map registered with framework
- `test_helpers/assertions.py` (157 LOC) — 11 entity assertion helpers + `assert_funder_report_has_no_version_fields`
- `test_helpers/factories.py` (154 LOC) — 11 payload factories, no computed fields
- `test_helpers/constants.py` (40 LOC) — eligibility weights, thresholds, speeds, 30-min buffer
- `test_helpers/test_users.py` (51 LOC) — shared constants + `make_provider_staff_headers(provider_id)`, `make_client_headers(client_id)`, `make_funder_reporter_headers(funder_id)` for entity-backed ownership threading
- `test_helpers/fixtures.py` (268 LOC) — atomic wrappers + `setup_baseline`, `setup_baseline_with_referral/accepted/service_in_progress`, `setup_program_at_capacity_utilization`, `setup_program_closed_by_capacity`, `setup_four_accepted_started_referrals`, `setup_three_unmet_outcomes_for_report`

test_suite/ (Stage 2):
- `test_suite/conftest.py` (42 LOC) — thin pytest fixture bridge
- `test_suite/test_01_difficulty.py` (875 LOC, 36 tests) — queue A
- `test_suite/test_02_corner.py` (538 LOC, 27 tests) — queue B

**Queue A coverage (Difficulty, 2 tests/instance):** all 9 rules × 2 instances × 2 tests = 36 tests.
**Queue B coverage (Corner, 1 test/non-stub instance):** entities 6/6, state_machines 6/6, calculations 4/4, validations 3/3, endpoints 2/2, errors 1/1, rbac 3/3, cross_cutting_complexity_layers 1/1, consistency_model 1/1 (2 excluded stubs cross-referenced to real Difficulty instances).
**Instances SKIPPED:** none — every non-stub instance had verbatim PRD coverage AND unique derivability; 63 test docstrings quote 60+ PRD passages that survive a literal 120-char-substring grep of PRD.md; no skip/skipif/xfail remains.

## Step 6: Generate implementation — 2026-07-04T19:01:00.000Z

result: Generated a complete Python + Flask implementation of the 211/findhelp Community Resource Directory API at `workspace/implementation/`.

**Files created** (21 files, 2,280 lines total):
- `start.sh` (10) — guarded `pip install`, `exec python3 app.py`
- `requirements.txt` (1) — `flask==3.0.3`
- `app.py` (62) — Flask entry, error handlers, `0.0.0.0:$PORT`
- `db.py` (26) — in-memory store; logical clock defaults to `2026-03-01T00:00:00Z` on every boot; no seeding
- `errors.py` (90) — 32-entry error catalog with HTTP status mapping and `ApiError` exception
- `response.py` (64) — success/error envelope helpers, `req_` id, ISO 8601 UTC with 3ms digits, offset/limit pagination
- `middleware.py` (43) — `X-User-ID`/`X-User-Role` auth extraction + `require_roles` decorator
- `services.py` (548) — entity constructors, serialisers, all six calculations (eligibility_score, travel_burden_minutes both variants, service_cost PROVISIONAL/FINAL, program_utilization, funder_report_allocation raw-float helper, funder_grant_ledger), state cascades (referral-withdraw, intake-close bubble-up, clock-advance consent-expiry, fiscal-year LOCKED→ARCHIVED, capacity increment/decrement with posture recompute + version bump)
- `util.py` (53) — UUIDs, ts format/parse, `half_up_2` and `half_up_int` via `Decimal(ROUND_HALF_UP)`, `floor_years_between`
- `validate.py` (110) — enum sets, body-shape helpers, pagination parser
- `routes/*.py` (10 modules, 40 endpoints total) — matches SCAFFOLD §1.5 exactly

**Notable design decisions**:
- Response envelope: `meta.api_request_timestamp` uses wall-clock (per PRD §2.2 "server-generated"); entity `created_at`/`updated_at`/`granted_at`/`expires_at` use the logical clock (per §2.9).
- `_touch()` bumps `version` and refreshes `updated_at`; capacity increment/decrement on a program always calls `_touch()` on the program (referral joining/leaving in-flight set is itself a program mutation).
- `FunderReport` is emitted without `updated_at` or `version` (PRD §2.4).
- Referral withdraw factored into `cascade_referral_withdraw` so `POST /consent-grants/{id}/revoke` reuses the exact same path (PRD §3.3).
- Body-FK-not-found (priority 11) uses `ERR_INVALID_REQUEST` (400); path-FK-not-found uses per-entity `_NOT_FOUND` 404s.
- `ERR_OUTCOME_ALREADY_REVERSED` is returned for both "already REVERSED" and "program ARCHIVED".

**Ambiguities resolved**:
- Referral cascade decrementing program capacity IS a program mutation → bumps `updated_at` + `version` on every capacity change.
- `Client` role authorised on `GET /programs/{id}` with no ownership tie — no ownership check applied on that endpoint (PRD §1.7 "read-only browse").
- Score of exactly 75.00 passes (`score >= 75.0`); capacity uses strict-less-than; income uses less-than-or-equal.

**Smoke-tested end-to-end via `bash start.sh`**: funder→provider→program→client→intake→screen→consent→referral (score 100.0, naive 16.65min, routed 22.48min for CAR); accept→start→complete→outcome; funder debit 100000→99000, reverse credit back to 100000; OCC stale-version returns 412; clock advance past `expires_at` cascades consent GRANTED→EXPIRED. All auth paths return correct envelopes.

## Step 7: Run tests and iterate — 2026-07-04T19:15:00.000Z

- **Iterations run**: 2 (initial sweep exposed 3 stable failures across all 8 rounds; second sweep after fixes: 8/8 rounds clean at 63/63).
- **Tests deleted**: none. All three failing tests trace to verbatim PRD sentences and pass the unique-derivability check.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to the test suite (`test_suite/test_02_corner.py`)**:
  - `test_create_referral_with_income_over_eligibility_max_returns_income_ineligible` — STEP 2 test-vs-PRD consistency. The original setup did not satisfy the PRD-mandated §3.4 priority precondition: `ERR_ELIGIBILITY_BELOW_THRESHOLD` (weight-27) fires before `ERR_INCOME_INELIGIBLE` (weight-29). With the setup as-written the score was 70.0 < 75.0, so the eligibility-score gate correctly tripped first. Added `intake_overrides={"presenting_needs": ["FOOD"], "urgency": "EMERGENCY"}` so the ×1.50 urgency multiplier lifts the score to 105.0, isolating the income check. The assertion was not weakened — it still requires the exact `ERR_INCOME_INELIGIBLE` id at 422.
- **Fixes applied to `implementation/`**:
  - `workspace/implementation/services.py::compute_travel_burden` — switched the distance × 111.0 / speed × 60 pipeline from IEEE 754 doubles to `Decimal(str(x))` end-to-end. Under floats, `|40.10-40.00|+|-74.05-(-74.00)| = 0.14999999...858`, yielding 24.97 after half-up; under decimals it yields exactly 0.15 → 24.975 → 24.98, matching PRD's decimal-literal semantics.
  - `workspace/implementation/routes/transport_plans.py` — the 30-minute buffer check used `min(gap_before, gap_after)`, which is always the deeply-negative directional difference and produced spurious conflicts even for non-overlapping intervals. Replaced with `separation = max(gap_a, gap_b); clamp to 0` — the true temporal separation, which is 0 on overlap and the positive gap otherwise. PRD §3.6 "gap of exactly 30 minutes is permitted" now passes at boundary.

result: task_0748_community_resource_directory — 8/8 parallel rounds pass 63/63 after two implementation fixes (Decimal travel-burden math, correct max-based transport-plan gap) and one test-setup fix (EMERGENCY urgency to satisfy PRD-mandated eligibility-score precondition).

## Step 8: Finalize PRD — 2026-07-04T19:20:00.000Z

**Line counts:** `PRD.md` 280 → `PRD_FINALIZED.md` 280 (2 in-place revisions, 0 inserted, 0 deleted).

**Changes:**
- §3.4 (travel-burden paragraph) — revise — pinned intermediate arithmetic of travel-burden pipeline to exact decimal-literal representations (as if `Decimal(str(x))`) rather than IEEE 754 float, so `|40.10−40.00|+|−74.05−(−74.00)|` yields exactly 0.15 — `implementation/services.py:215-238` (`compute_travel_burden`).
- §3.6 (transport 30-minute buffer sentence) — revise — replaced "smaller of the two temporal gaps" with "true temporal separation" clamped to 0 on overlap, with the equivalent `max(gap_a, gap_b, 0)` closed form spelled out — `implementation/routes/transport_plans.py:77-83`.

**Per-edit pre-edit search log:**

Edit 1 — travel-burden decimal arithmetic (§3.4):
- (a) Subject: exact-decimal vs. binary-float representation of the distance × 111.0 × [1.35] / speed × 60.0 pipeline that produces `travel_burden_naive_min` / `travel_burden_routed_min`.
- (b) Enumerated impl paths: `services.py::compute_travel_burden` (Decimal end-to-end); `compute_eligibility_score` (plain float + half_up_2 at boundary); `compute_service_cost_final` / `raw_cost_float` (plain floats); `funders.py:124` `half_up_int(raw_total)` (float sum); `util.py::half_up_2/int` (float→Decimal only at final quantize); `referrals.py:145` (only calls compute_travel_burden).
- (c) Wording adjustment: scoped the new sentence explicitly to "this travel-burden pipeline" and enumerated the exact operations covered so eligibility-score / service-cost / funder-report float paths are NOT accidentally covered. Used "as if each were materialised via `Decimal(str(x))`" so any equivalent exact-decimal path is compliant.

Edit 2 — transport 30-minute buffer semantics (§3.6):
- (a) Subject: how the two same-client SCHEDULED transport plans' "temporal gap" is defined, and the sign / clamping.
- (b) Enumerated impl paths: `transport_plans.py::create_plan` (only gap-computing site, uses `separation = max(gap_a, gap_b)` clamped to 0, compared `< BUFFER_SECS = 30*60`); `services.py::make_transport` (no gap logic); `cascade_referral_withdraw` (no gap logic); `db.py::transport_plans` (storage only). Also verified §2.9 existing prose is consistent with new §3.6 wording.
- (c) Wording adjustment: used "true temporal separation" matching impl's own comment; added the explicit `max(gap_a, gap_b, 0)` closed form and the "regardless of the magnitude of the overlap" qualifier so a deeply-negative directional difference cannot be mis-read; kept boundary rule verbatim ("separation of exactly 30 minutes is permitted").

result: PRD_FINALIZED.md written — 2 in-place revisions (lines 154 §3.4 travel-burden decimal arithmetic; 178 §3.6 transport-buffer "true temporal separation"), 280→280 lines, both tracing to `<step_7_diff>` implementation fixes and no third fixture-only item requiring PRD change.

## Step 9: Complete PRD — 2026-07-04T19:26:00.000Z

**Source vs completed:** PRD_FINALIZED.md 280 lines / 50,212 chars → PRD_COMPLETED.md 280 lines / 55,054 chars (+4,842 chars, no lines added/removed — all in-line edits).

**Counts:** 10 ambiguity-pins, 4 mismatch-revisions, 14 total edits (one bullet occasionally combines multiple in-line edits at the same section).

**Per-change list:**
- §2.1 RBAC — insert — ambiguity — pinned list-endpoint ownership scoping (silent filter, not error) for `GET /consent-grants` (Client, ProviderStaff) and `GET /referrals` (ProviderStaff) — routes/consent_grants.py:76-79, routes/referrals.py:179-183
- §2.2 Success Response — revise — ambiguity — pinned `api_request_id` shape as `req_` + 20 chars from A-Z0-9 (24 total) — response.py:19-21
- §2.2 Success Response — revise — ambiguity — pinned `api_request_timestamp` uses wall-clock time (not logical clock) at response emission — response.py:24-29
- §2.2 Success Response — revise — ambiguity — pinned pagination `meta` fields appear only on list endpoints; non-list and error `meta` carry only id and timestamp — response.py:32-53
- §2.4 Common Resource Properties — insert — ambiguity — pinned domain timestamps read from logical clock (not wall-clock) — services.py:26-37, 508
- §2.9 Temporal Semantics — revise — ambiguity — pinned clock-set response shape `{"current_utc": ...}`, HTTP 200; consent-expiry and program-archive side effects touch version/updated_at; rollover uses strict-after old and at-or-before new; rewind accepted, cascade only forward — routes/clock.py:11-18, services.py:373-412
- §3.1 Program patch — revise — ambiguity — pinned patch fields optional except `expected_program_version`; age-band invariant re-check; capacity_slots_total change recomputes posture; version always bumps — routes/programs.py:117-159
- §3.2 Intake reopen — insert — ambiguity — pinned in-flight-referral check yields `ERR_REFERRAL_INVALID_STATE` (HTTP 409); order is state check → referral check — routes/intakes.py:88-97
- §3.4 Referral creation side effects — revise — mismatch — pinned that program `version` always bumps on capacity mutation (impl `_touch` in `increment_capacity` fires regardless of posture change) — services.py:320-326
- §3.5 Referral acceptance — revise — ambiguity — pinned fixed check order: state → posture → consent (impl checks CLOSED before consent) — routes/referrals.py:207-218
- §3.5 Referral decline — revise — mismatch — pinned capacity decrement clamped at 0; program version always bumps regardless of posture change — services.py:329-337
- §3.5 Referral completion — revise — mismatch — pinned `outcome_class` other-value error is `ERR_INVALID_REQUEST`; capacity clamp; program version always bumps — routes/referrals.py:260-269, services.py:329-337
- §3.5 Client withdrawal — revise — mismatch — pinned transport-plan cancellation cascade runs unconditionally (impl `cascade_referral_withdraw` doesn't gate on prior state); capacity clamp; program version always bumps — services.py:540-560
- §3.7 Outcome file — revise — ambiguity — pinned no referral-state precondition; multiple ACTIVE outcomes allowed; `service_hours` accepts JSON int or float — routes/outcome_reports.py:47-82
- §4 Endpoint Table — revise — ambiguity — pinned `/referrals/{id}/transport-plans` GET applies no per-caller ownership scoping — routes/transport_plans.py:90-98
- §4 Endpoint Table — revise — ambiguity — pinned `/referrals/{id}/outcome-reports` GET applies no per-caller ownership scoping — routes/outcome_reports.py:84-92

result: PRD_COMPLETED.md written — 14 in-line edits (10 ambiguity pins, 4 mismatch revisions) over PRD_FINALIZED.md; same 280 lines, +4842 chars.
