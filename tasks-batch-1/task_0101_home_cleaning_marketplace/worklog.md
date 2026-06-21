# Worklog — task_0101_home_cleaning_marketplace

## Step 1: Create task directory — 2026-06-02T14:57:24.000Z

Created `tasks/task_0101_home_cleaning_marketplace/` with `workspace/` subdirectory. Index 0101 pre-assigned (no tasks/ scan, to avoid collision with 5 concurrent sibling pipelines). Scenario: Home Cleaning Marketplace (Expert difficulty).

## Step 2: Generate scaffold — 2026-06-02T15:21:00.000Z

Generated three lint-clean scaffold artifacts for **task_0101_home_cleaning_marketplace** (Expert difficulty), all written to the task dir:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts:**
- **Entities: 11** (Customer, Address, Cleaner, BackgroundCheck, PricingPlan, BookingSeries, Booking, PreferredPro, Tip, CleanerPayout, LedgerEntry) — within the Expert 10–15 band.
- **Endpoints: 46.** Exceeds the Expert 20–32 ceiling. The overage is structural and intentional: a flat-topology design with 11 entities, many multi-FK leaf entities (Tip, LedgerEntry, CleanerPayout, PreferredPro), requires a single-resource GET plus a filtered-list GET per entity to satisfy FK reverse-reachability (lint check (f)). Per project memory, accept lint-clean overage rather than distort the design; 25 of 46 are POST action/create endpoints driving the actual coupling.
- **State machines: 3** (Cleaner — branching fork + reinstatement loop; BookingSeries — self-loop generation + cascade cancel; Booking — reschedule revision cycle + reclean branch).
- Calculations: 6; Validations: 16 (priority-ordered); Errors: 16; Roles: 4; Concurrency rules: 2 (OCC on BookingSeries and PricingPlan versions).

**Design coverage:** All nine §0.5 Difficulty Rules satisfied with exactly 2 instances each = 18 difficulty instances; 32 corner instances spanning all nine claim-extraction sections. Every one of the 16 error codes positively triggered in ≥1 design instance. Two test-driving endpoints under `/_<name>` (`/_clock/set_current_utc`, `/_loyalty/set_count`).

**Linter:** `scaffold_lint.py` reports `VERDICT: clean lint` — all 496 §1.8/§1.9 calls conform to §1.5, all §1.1 FKs have reverse-reachability. File split honored, no forbidden concurrency vocabulary, all instance names unique, all formula-derived assertions pre-computed as literals.

One correctness issue caught and fixed during self-review: an early `ERR_CLEANER_NOT_CLEARED` definition was unreachable (subsumed by `ERR_INVALID_STATE` on the terminal CHECK_FAILED path); repurposed to guard pinning a non-ACTIVE cleaner on a booking, and rebuilt the affected priority-conflict instance as a genuine auth-ownership vs business-safety dual-failure.

## Step 3: Copy INSTRUCTION.md — 2026-06-02T15:21:35.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-02T15:26:37.000Z

Generated `workspace/PRD.md` — a 262-line prose PRD for the Home Cleaning Marketplace API from `SCAFFOLD.yaml`.

**Sections covered:**
- §1 Introduction (business-context angle)
- §2 Global Specifications — 10 subsections: RBAC (all four roles, each identity translated), §2.2 fixed verbatim response envelope, pagination, common-properties/versioning (Tip and LedgerEntry flagged `common_fields: false` — id + created_at only), existence ordering, validation ordering, OCC, monetary precision, ledger invariant, cascading propagation
- §3 Business Logic — 7 domain-grouped subsections (cleaner onboarding, customers/addresses/plans, one-time bookings, recurring series, reschedule/cancel window fee, pricing engine, completion/payouts/tips/guarantee), endpoint parameters scattered across subsections
- §4 Endpoint table (4 columns, 44 endpoints)
- §5 Error catalogue (2 columns, 16 errors)

**Hard Contracts — all PASS:**
- Contract 1 (Field-Name Coverage): 0 missing; 54-name required set all verbatim in backticks.
- Contract 2 (Rule Coverage): all 16 error IDs, 16 states, 15 enum values, all numeric constants (visit durations 90/120/150/180/240, fee bands 48/12h, flat 1500, move-out floor 20000, 72h reclean window, 30-min travel buffer, 7/14-day cadence, 70%/25%/50% and loyalty 0/5/10/15% inclusive boundaries) present; both OCC rules express write-action + expected_*_version + ERR_STALE_VERSION/412; cascades, validation priority ordering, payout/tip recompute, net-refund conservation all stated.
- Contract 3 (§3 Path Purity): 311 §3 tokens scanned, 0 slash-prefixed, 0 bare-method, 0 method+path.

**Confirmation:** Neither design file was read/opened/grepped/referenced; no sibling task directory accessed.

## Step 5: Generate unit tests — 2026-06-02T15:39:20.000Z

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts; `Tip` and `LedgerEntry` carry only `id`+`created_at`, no `version`/`updated_at`), `api_client.py` (one method per endpoint), `api_errors.py` (16 error IDs registered with HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_customer_headers`/`make_cleaner_headers` builders), `fixtures.py` (composite setup tiers: booking worlds, completed/reclean lifecycles, series with occurrences, two-cleaner worlds), barrel `__init__.py`.

**Stage 2 — `test_suite/`** (`conftest.py` + 7 test files).

**Counts:** Test files: 7 (+conftest). Test functions: **68**. Every test carries exactly one `Design:` tag (0 untagged, 0 dual-tagged, every tag resolves to a real instance).

**Coverage:** Queue A (Difficulty): 18/18 instances, each ≥2 tests. Queue B (Corner): 32/32 non-stub instances, each ≥1 test (0 `excluded_because:` stubs). **Skips: 0.** Every instance passed the PRD-first two-condition filter (pricing formulas, per-component rounding, loyalty tiers, window-fee bands, double-booking geometry, §2.6 precedence chain, OCC, cascades, ledger/payout conservation invariants all verbatim+uniquely-derivable). Two validation-priority conflict instances PRD-derivable via §2.6 ordering.

**Verification:** all 68 tests collect under pytest; framework validator signatures confirmed; each docstring contains a verbatim ≥8-word PRD substring; no scaffold/§1.x/Table leakage; no skip/skipif/xfail markers.

## Step 6: Generate implementation — 2026-06-02T15:39:20.000Z

Generated complete Python + Flask implementation in `workspace/implementation/` (27 files).

**Files:** `start.sh` (foreground launcher, flask-import-guarded install), `requirements.txt` (flask==3.0.3), `app.py` (blueprints, global error handlers, binds `0.0.0.0:$PORT`), `db.py` (in-memory dict store + common-field stamping), `errors.py`/`response.py`/`auth.py`/`helpers.py`/`serializers.py`/`constants.py`/`clock.py`/`util.py`, `routes/` (customers, addresses, cleaners, pricing_plans, preferred_pros, booking_series, bookings, tips, payouts_ledger), `services/` (calc, assignment, collisions, ledger, booking_ops).

**Endpoints:** 46 — exact 1:1 match with scaffold endpoint table (0 missing, 0 extra), verified by automated diff.

**Behavior verified (live smoke, 59 checks green):** response envelope, pagination meta, ISO8601 3-digit fractional; auth 401/RBAC 403/ownership 403/existence-left-to-right 404/state-gate 409; cleaner onboarding state machine + terminal CHECK_FAILED; pricing (home-size base, per-component rounded surcharges, supplies fee, loyalty tiers, MOVE_OUT floor 20000); window fees (free/late/no-show, reschedule flat 1500, cancel 25%/50%, refund+CHANGE_FEE conservation); payout 70% + tip fold-in + single-tip guard; reclean branch (0-priced is_reclean booking + RECLEAN_CREDIT); series generation w/ OCC (`expected_series_version`), cadence +7/+14d, cascade-cancel non-terminal children; plan activation OCC (`expected_plan_version`), single-active invariant; double-booking (cleaner buffer-extended 30min half-open, address raw half-open); validation precedence per §2.6.

**Constraints confirmed:** storage in-memory only (module-level dicts, no SQLite/JSON/tmp; fresh boot → empty state); no seeding/preloading; `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground, pip guarded behind `import flask` sentinel. Targeted Python 3.9 compatibility (env has 3.9.6).

## Step 7: Test and iterate to green — 2026-06-02T15:48:00.000Z

**Iterations run:** 3 sweeps (1 baseline + 2 verification). Baseline: 7 stable failures (identical across all 8 rounds — not flaky, all PRD-logic bugs). Final: 68/68 passing across all 8 parallel rounds.

**Tests deleted:** None. Every failure traced to a real implementation bug or a fixture/test precondition inconsistent with PRD prose — none failed the PRD-coverage or unique-derivability checks.

**Fixes applied to implementation/:**
- `routes/bookings.py` — `schedule_reclean()`: the endpoint returned the *original* booking (now terminal `RECLEAN_SCHEDULED`) instead of the **spawned** reclean booking. PRD §3.7 states the operation "spawns a brand-new booking" carrying `is_reclean=true`, `quoted_price_cents=0`, `reclean_of_booking_id`, copied `cleaner_id`. Changed return to `S.booking(reclean)` (kept status 200, which the test's `validate_success` default requires). Single fix resolved 4 failures: `test_schedule_reclean_spawns_assigned_zero_priced_booking`, `test_schedule_reclean_writes_zero_valued_reclean_credit_marker`, `test_reclean_completion_payout_is_zero` (fixture stored the wrong booking as `reclean_booking`), `test_referential_beats_temporal_on_request_reclean` (completed `spawned["id"]`, previously terminal original → "not completable").

**Fixes applied to test_helpers/ and test_suite/ (PRD-consistency, STEP 2):**
- `test_helpers/fixtures.py` — `setup_series_with_one_occurrence()`: fixture called `generate` with clock at booking-world default `2026-06-01` while series' `next_occurrence_date` was `2026-06-20`. PRD §3.4 permits generation only when `next_occurrence_date` ≤ current clock, so PRD-faithful impl correctly rejected with `ERR_INVALID_STATE`. Added `set_clock(first_occurrence_date)` before generate. Fixed 2 failures: `test_series_cancel_cascades_to_booking_cancel_and_refund`, `test_series_cancel_sets_terminal_state_and_nulls_next_date`.
- `test_suite/test_07_crud_rbac_concurrency.py` — `test_stale_series_version_on_generate_rejected`: same clock issue plus a precedence interaction. A successful generate advances both `version` and `next_occurrence_date` (PRD §2.7), so a second stale-version generate left the due-date no longer satisfied, and impl's `ERR_INVALID_STATE` due-date gate fired before the version check, masking `ERR_STALE_VERSION`. Rather than weaken the assertion, made it MORE faithful: advanced the clock to the *new* occurrence instant (`2026-06-27`, first + WEEKLY 7-day step) so the due-date precondition is satisfied and the stale `expected_series_version` is the sole failing precondition, isolating `ERR_STALE_VERSION` deterministically.

All storage remains in-memory (Python dicts); no seeding or persistence introduced. No PRD-required implementation checks weakened.

## Step 7b: Orchestrator confirmation sweep — 2026-06-02T15:49:50.000Z

Re-ran the 8-round parallel sweep independently (orchestrator-owned) to confirm green and persist final artifacts after the subagent's per-iteration `rm -f`. Result: results.1–8.json all `passed=68 total=68`. ALL GREEN. Final stability artifacts persisted in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-02T15:52:00.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch over `PRD.md`. Line counts: PRD.md = 262, PRD_FINALIZED.md = 262 (one existing §3.7 prose line extended in place, no line added/removed; one inserted sentence).

**Change (single bullet):**
- §3.7 (Satisfaction Guarantee / schedule-reclean) — *insert* — Pinned which booking the schedule-reclean endpoint returns: its `200 OK` response body returns the spawned brand-new re-clean booking, not the transitioned original — `routes/bookings.py:298` (`return success(S.booking(reclean), status=200)`).

**Why only one edit:** The `<step_7_diff>` contained a single `implementation/` fix (schedule-reclean return value). The other two diff items (test_helpers/fixtures.py, test_07) were pure fixture/test precondition bugs — impl was already PRD-faithful (§3.4 due-date gate and §2.7 stale-version rule already fully pinned). The schedule-reclean return value was the only genuine PRD silence: §2.2's default ("operations that create or modify a resource will return the created or updated resource object") is ambiguous for an operation that both spawns one booking and transitions another; impl resolves toward the spawned booking.

**Pre-edit search log (Edit 1, §3.7 return value):**
- (a) Subject: response body (which booking object + HTTP status) of `POST /cleaning/bookings/{id}/schedule-reclean`.
- (b) Impl paths: grepped `schedule_reclean|schedule-reclean` across implementation/**/*.py — sole def `routes/bookings.py:268-298`, single return at 298 (`success(S.booking(reclean), status=200)`); read `services/booking_ops.py:create_booking_record` (reclean spawn 43-99); read `serializers.py:booking`. Cross-checked §2.2 default-return (line 51), §4 201/200 classification (line 192; schedule-reclean not in 201 list → 200), and sibling create+mutate series-generate (§3.4/§2.7, 201) to ensure wording does not bleed onto it.
- (c) Wording: scoped sentence to "the schedule-reclean call", named returned object "the spawned brand-new re-clean booking — not the transitioned original"; pinned `200 OK` to match impl line 298 and §4. No widening needed (single return path).

## Step 9: Complete PRD — 2026-06-02T15:57:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan. Source `PRD_FINALIZED.md` (262 lines / 39,500 chars) → `PRD_COMPLETED.md` (262 lines / 41,251 chars). Char-delta +1,751. No line-count change (all in-paragraph). Counts: 3 mismatch-revisions, 6 ambiguity-pins.

**Per-change list:**
- §3.1 Cleaner Onboarding — revise — mismatch — PRD claimed `email` "unique across cleaners"; impl never enforces uniqueness. Revised: emails lowercased but duplicates accepted — `routes/cleaners.py:30-39`.
- §3.2 Customers — revise — mismatch — same email-uniqueness mismatch for customers — `routes/customers.py:36-43`.
- §3.3 One-Time Bookings — insert — ambiguity — pinned `change_fee_cents` init-0 + overwrite-with-latest (not running total) — `services/booking_ops.py:87`, `routes/bookings.py:147`.
- §3.4 Recurring Series — insert — ambiguity — pinned `ERR_INVALID_STATE` when generating not-yet-due / null `next_occurrence_date` — `routes/booking_series.py:132-133`.
- §3.5 Rescheduling — insert — ambiguity — pinned reschedule fee measured against pre-move `scheduled_start`, not new instant — `routes/bookings.py:144-146`.
- §3.5 Rescheduling — insert — ambiguity — pinned `ERR_NO_CLEANER_AVAILABLE` and noted status not re-verified for pinned-cleaner postal recheck — `routes/bookings.py:127-132`.
- §3.7 Completion — insert — ambiguity — pinned `ERR_INVALID_STATE` when completing before `scheduled_start` — `routes/bookings.py:198-199`.
- §3.7 Completion (re-clean) — revise — mismatch — clarified "does not bump either counter" excludes only the two named counters; `rating` still folds into `rating_sum`/`rating_count` — `routes/bookings.py:221-230`.
- §3.7 Satisfaction Guarantee (schedule-reclean) — insert — ambiguity — pinned spawned booking's `scheduled_start` source, copied `add_ons`/`supplies_provided_by`, collision-check skipping — `routes/bookings.py:276-291`, `services/booking_ops.py:61-63`.
- §3.7 Test-driving clock — insert — ambiguity — pinned wall-clock-UTC fallback + set-clock `200 OK` empty `data` — `clock.py:17-20`, `routes/customers.py:97`.

**Verified non-changes:** credit-adjustment 201 + loyalty-seed/clock 200 covered by §4; CleanerPayout carrying version/updated_at follows §2.4 (only Tip and LedgerEntry append-only); reschedule writes only CHANGE_FEE (no REFUND), matching §3.5; collision checks run on creation/generation/reschedule per §3.5.

## Pipeline complete — 2026-06-02T15:57:00.000Z

All 9 steps done. Final state: 68 tests, 8/8 parallel rounds green (68/68 each). Artifacts: SCAFFOLD.yaml (+ 2 design files), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_suite/ + test_helpers/, workspace/implementation/ (in-memory Flask, 46 endpoints), results.1–8.json.
