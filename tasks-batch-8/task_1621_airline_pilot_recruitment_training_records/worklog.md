# Worklog — task_1621_airline_pilot_recruitment_training_records

## Step 1: Create Task Directory — 2026-08-14T02:17:00.000Z

Pre-assigned directory `tasks/task_1621_airline_pilot_recruitment_training_records/` with `workspace/` subdirectory confirmed present. Treated as DONE per pipeline instructions; no index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-14T02:18:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1621_airline_pilot_recruitment_training_records/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T03:10:00.000Z

## Summary

Generated a fresh Expert-band scaffold for **task_1621_airline_pilot_recruitment_training_records** purely from the scenario + skill spec (no sibling tasks inspected). All three artifacts are in place and pass `scaffold_lint.py` with a clean verdict:

- `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: **15** (spec maximum), incl. append-only `CostLedgerEntry` (`common_fields: false`)
- State machines: **11** machine entries covering 10 entities — Enrollment (retraining cycle IN_PROGRESS↔REMEDIATION, DISQUALIFIED→REMEDIATION), Qualification (currency cycle QUALIFIED→WARNING→LAPSED→REQUALIFYING→QUALIFIED **plus** parallel `operating_state` dimension), Applicant (REJECTED→SCREENING appeal loop), plus RecordsRequest, TrainingClass, TrainingEvent, Checkride, MedicalCertificate, BidPeriod, Bid, SimulatorSlot
- Calculations: **6** — `class_seat_forecast` (dual-variant + pinned evaluation order, mode c), `training_footprint_cost` (provisional-vs-final dual variant + per-line-then-sum rounding, mode b), `currency_recency_check` (multi-branch 90-day half-open lookback, mode a), `bid_award_ranking` (seniority ranking with pinned tie-break, no id usage), `medical_validity_window` (age-branched calendar-month expiry), `seniority_assignment`
- Endpoints: **82** (guideline-busting but every one load-bearing; includes `/_ops/run-daily-scan` and `/_clock/set-current-utc` with the pinned default `2026-08-01T00:00:00Z`)
- Errors: **44**, all referenced by ≥1 validation/transition
- Validations: **44** rows, priority-ordered (auth → existence → state → safety → referential → temporal → constraint → fiscal/seat-gate → OCC last)
- Roles: **6** (Recruiter/TrainingCoordinator/CrewScheduler/SystemAdmin opaque; Pilot→Applicant and CheckAirman→Instructor entity-backed; segregation-of-duties airman-conflict rule)
- §1.8: **18 instances** (9 rules × 2), every one with fully structured, replayed setup chains
- §1.9: **47 active instances + 2 excluded stubs** across all nine guide sections
- Lint: **clean** (1085 calls scanned, 0 violations; all FKs reverse-reachable)

**Design decisions of note**
- **True-race OCC only**: both concurrency rules sit on `TrainingClass.version` (enrollment-create and attrition PATCH) — both pass the serial-observability filter since the class stays OPEN after a successful write. A bid-award OCC variant was deliberately rejected (award success changes period state → state precondition, not a race).
- **Attrition-overbooking seat gate**: `max_seats_sellable = floor(capacity × (1 + attrition))` with strict `<`, PATCHable attrition that can flip `over_committed`, and Rule-6 boundary pinned at the exact floor boundary (cap 2 × 0.50 = exactly 3).
- **Half-open vs buffer interval semantics** for Rule 8: simulator slots use containment + half-open `[start,end)` (adjacency legal); instructors require a ≥30-minute gap (adjacency illegal).
- **Compensating invariants** pinned as explicit formulas: seat counters (`confirmed_count`/`active_enrollment_count` vs status sets) and money (`ledger_balance_cents` = signed Σ of ledger entries; verify literal 390000→0 reversal).
- **Cascade chains**: class-cancel depth-3 (Class→Enrollment→CostLedgerEntry→Applicant balance) and medical-grounding depth-2+ (Certificate→Qualification→TrainingEvent), both spelled out in transition side-effects.
- Dual-variant divergence numbers were pre-computed as literals (e.g., walk 3 vs aggregate 2; provisional 0 vs final 150000; per-line rounding 525006 vs 525005).
- One scaffold refinement during QA: class cancel is legal from SCHEDULED/OPEN/**IN_SESSION** so the depth-3 cascade carries money; checkride PASS upsert no longer stomps an existing qualification's `currency_state` (only creates or refreshes `operating_state`), keeping the requalification cycle reachable.

## Step 4: Generate PRD — 2026-08-14T03:30:00.000Z

PRD generated and all three hard contracts verified. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/workspace/PRD.md` — 336 lines

**Section list:**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (verbatim canonical block, byte-identical), 2.3 Pagination, 2.4 Logical Clock & Daily Operations Scan, 2.5 Resource Identity/Timestamps/Version, 2.6 OCC on Training Classes, 2.7 Money/Rounding/Append-Only Ledger, 2.8 Validation Order & Error Precedence, 2.9 State Machines/Parallel Dimensions/Cascades
- 3. Business Logic & Workflows — 3.1 Screening & PRIA Pipeline, 3.2 Fleet/Classes/Attrition Seat Forecast, 3.3 Enrollment Lifecycle & Retraining Loop, 3.4 Instructors/Slots/Event Scheduling, 3.5 Checkrides/SoD/Qualification Upsert, 3.6 Qualifications/Currency/Flight Activity/Medical Gate, 3.7 Bid Periods & Seniority Awarding, 3.8 Cost Accounting/Rate Card/Footprint Variants
- 4. Endpoint Definitions (82 rows, 4 columns)
- 5. Error Code Catalogue (44 rows, 2 columns)

**Contract 1 — Field-Name Coverage: PASS.** Entity fields 81/81, endpoint inputs 56/56, computed-output identifiers 10/10 — all appear backticked in prose.

**Contract 2 — Rule Coverage: PASS.** Verified by full scaffold walk: all 18 validation priority levels expressed as an explicit first-failure-wins evaluation order (§2.8) plus per-endpoint orderings in §3 (clear: records-before-medical; enrollment create: existence → class-OPEN → duplicate → seat gate → OCC-last; event scheduling: full 9-step stack; record-outcome: identity → state → conflict → medical); both OCC rules named with `expected_training_class_version` + `ERR_STALE_VERSION`/412; all 11 state machines' transitions (from/to/preconditions/side-effects, including the Qualification dual-dimension legs and the cyclic appeal/retrain loops); all 6 calculations in precise prose with constants embedded (1,500 hours, 30/90/83/365-day windows, 80 score, 2-attempt ceiling, 30-minute buffer, 150,000/120,000/9,000-cent rate card, 0.25 surcharge, 0.90–0.98 phase survivals, 12/6 and 60/24 medical month branches, pinned evaluation and rounding orders, both forecast and footprint variants); all cascade chains link-numbered; all `applies_to` scopes enumerated; defaults/nullability structured content stated (including `CostLedgerEntry` carrying only `id`/`created_at`); sibling branches rendered with equal density.

**Contract 3 — §3 Path Purity: PASS.** 557 backticked tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos.

Additional checks: all 44 error IDs mentioned in §2/§3 and tabulated in §5; all 65 enum/state values present as exact strings; no pseudocode operators or fuzzy wording in §1–§3 prose.

## Step 5: Generate Unit Tests — 2026-08-14T04:10:00.000Z

Generation complete. All 81 tests collect cleanly under pytest with the runner's PYTHONPATH convention.

## Summary

**Test count: 81 total** — Queue A (§1.8 difficulty): 34 tests covering 17 instances (2 each). Queue B (§1.9 corner): 47 tests covering all 47 non-stub instances (1 each). Both corner stubs (`class_seat_forecast_input_set_excludes_terminal_enrollments`, `bid_award_excluded_covered`) were verified to resolve to live difficulty instances and not translated.

**Skipped instance (1):**
- `Difficulty/cross_entity_state_dependency/enrollment_requires_applicant_cleared` — fails PRD coverage. It asserts POST /enrollments rejects a PRIA_VERIFIED applicant with ERR_APPLICANT_INVALID_STATE, but PRD §3.3 pins the enrollment gate order (existence → class OPEN → duplicate pair → seat gate → OCC) with no applicant-status gate anywhere in the document; a PRD-only implementer would return 201. Gap left as a gap.

**Recipe bugs repaired in place (rule kept, asserted values PRD-derived):**
- `seat_gate_pinned_evaluation_order_after_attrition_patch`: the trigger re-enrolled an already-enrolled applicant, which trips ERR_DUPLICATE_ENROLLMENT (gate 3) before the seat gate (gate 4) under PRD §3.3's pinned order. Added a fourth cleared applicant so the asserted ERR_CLASS_FULL is uniquely derived.
- `medical_validity_age_branch_40_plus_vs_under`: the recipe's age-40 first-class through-date (2026-07-31) contradicts the PRD formula under any reading; corrected to 2027-01-31 (issue month + 6 months), the reading pinned by the companion difficulty instance's working setup (issued 2026-02 age 45 → through 2026-08-31).
- `qualification_currency_cycle_with_parallel_operating_dimension`: recipe opened a class dated 2026-08-10 after advancing the clock to 2026-08-14 (open requires a future class date); shifted the class date to 2026-08-14T12:30, asserted outcomes unchanged.

**Helper files generated** in `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/test_helpers/`: `types.py` (15 entities; CostLedgerEntry omits updated_at/version), `api_client.py` (~70 endpoint methods under /pilot-training), `api_errors.py` (45 error IDs + status map registered with the framework), `assertions.py` (per-entity asserts incl. ledger absence-of-version, instant-compare helpers), `factories.py`, `constants.py`, `test_users.py` (opaque role constants + `make_check_airman_headers`/`make_pilot_headers` entity-backed builders), `fixtures.py` (screening-to-CLEARED chain, class/enrollment OCC-aware enrollment, phase-advancement chains through GROUND→SIMULATOR→CHECKRIDE→IOE, bid-period helpers, ledger readers), `__init__.py` barrel.

**Test files** in `test_suite/`: `test_01` applicants/records (19), `test_02` classes/seats/OCC (15), `test_03` events/billing (19), `test_04` checkrides/retraining (8), `test_05` qualifications/medical/currency (11), `test_06` bids/awards (5), `test_07` RBAC (4).

**Stage 2 self-check results:** every test carries exactly one `Design:` tag resolving to a real instance; all difficulty instances have ≥2 tests, all non-stub corner instances ≥1; every ≥8-word docstring citation span survives a whitespace-normalized verbatim grep of PRD.md (0 failures, including manually verified nested-quote citations); no `skip`/`skipif`/`xfail` marks; pyflakes clean; py_compile clean; 81/81 collected by pytest. Timestamp assertions compare parsed instants rather than exact strings, since PRD's three-fractional-digit rendering rule names only `created_at`/`updated_at`/meta timestamps (asserted strictly there) and not `sent_at`/`due_at`/`lapsed_since`.

## Step 6: Generate Implementation — 2026-08-14T04:10:00.000Z

The implementation is complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/workspace/implementation/`:

- `start.sh` — guarded launcher (`python3 -c "import flask"` check before pip install; `exec python3 app.py` foreground; `PORT` env, default 10000, binds `0.0.0.0`)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app, blueprint registration under `/pilot-training`, ApiError + 404/405/exception handlers
- `db.py` — in-memory `Store` (15 dicts keyed by id, insertion sequence, logical clock defaulting to exactly `2026-08-01T00:00:00Z`); fresh process = empty store, zero seeding
- `errors.py` — full 43-entry error catalog with exact IDs and HTTP statuses
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`, defaults 10/0, min 1, max 100), ISO-8601 rendering with 3 fractional digits, body/type validators
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, six roles, per-endpoint role lists
- `services.py` — serializers, entity lookups with per-entity 404 codes, all calculations and cascades
- `routes/` — `applicants.py` (applicants + records requests + footprint), `classes.py` (equipment, classes, enrollments), `events.py` (training events, checkrides), `quals.py` (qualifications, flight activities, medicals), `bids.py` (bid periods, bids), `resources.py` (instructors, simulator slots, cost ledger), `ops.py` (daily scan, logical clock)

## Endpoint coverage
**82/82** PRD endpoints implemented (counted against the §4 table: 15 applicants/records, 21 equipment/classes/enrollments, 11 events/checkrides, 13 quals/activities/medicals, 11 bid-periods/bids, 9 instructors/slots/ledger, 2 ops/clock).

## State machines implemented (11)
Applicant (screening pipeline incl. appeal loop, withdrawal expiring DRAFT/SENT requests), RecordsRequest (DRAFT→SENT→RECEIVED→VERIFIED + FAILED + scan/withdrawal EXPIRY, with PRIA bubble-up), TrainingClass (open/start/complete/cancel with 3-link cancel cascade), Enrollment (full retraining loop: REMEDIATION⇄IN_PROGRESS, DISQUALIFIED→REMEDIATION with failed_attempts ≤ 2 ceiling, withdrawal reversals + event cancellation), TrainingEvent (complete/fail/cancel with billing), Checkride (PASS/FAIL cascades, attempt numbering), Qualification (parallel `currency_state` + `operating_state` dimensions; LAPSED never returns via refresh — only requalify/certify; LAPSED→EXPIRED at 365 days), MedicalCertificate (monotone VALID→DOWNGRADED→EXPIRED + terminal SUSPEND with grounding cascade), BidPeriod (DRAFT→OPEN→CLOSED→AWARDED→FINALIZED + scan auto-close), Bid (award/deny/withdraw), SimulatorSlot (AVAILABLE⇄MAINTENANCE toggle blocked by live bookings).

## Calculations implemented (6)
- `class_seat_forecast` — pinned order; `max_seats_sellable=floor(cap*(1+rate))`, aggregate floor variant + per-enrollment chronological walk (email tie-break, phase survival table) rounded half-up; `over_committed` gate
- `training_footprint_cost` — rate card (GS 150000 flat, SIM duration×equipment rate, IOE duration×9000, checkride 120000, FAIL +30000 surcharge), per-line `Decimal` ROUND_HALF_UP before summing; provisional (signed ledger sum) vs final (recompute-from-source, ignores REVERSALs) variants
- `currency_recency_check` — half-open `(now-90d, now]` window, oldest-7-day expiring band, QUALIFIED/CURRENCY_WARNING/LAPSED branches
- `bid_award_ranking` — eligibility filter (CLEARED + VALID FIRST medical), seniority_snapshot ASC, cleared_at ASC, email ASC tie-breaks; winners set `current_equipment_id`, losers DENIED/INSUFFICIENT_SENIORITY, ineligible DENIED/INELIGIBLE
- `medical_validity_window` — whole-calendar-month arithmetic (12/6 and 60/24 by age-40 branch), inclusive last-day-of-month through-dates, date-granularity status evaluation at issue and per scan
- `seniority_assignment` — gapless `1 + count(existing seniority holders)` at CLEARED

Also: OCC via `expected_training_class_version` (412, checked last) on enrollment create + class PATCH; validation priority order 1–18 honored (auth → role/identity → existence → state → SoD → medical gate → currency gate → clear-gate referential → tier → slot containment/overlap → 30-min instructor buffer → scheduling window → daily capacity → flight hours → constraint band → seat gate → OCC); version bumps exactly per the scaffold's side-effect lists (scan/cascade transitions refresh `updated_at` only, except bid-period auto-close).

## Boot sanity check
Cold-launched `bash start.sh` on scratch port 18077 from a fresh process: ready in ~1s, unauthenticated probe correctly returned `401 ERR_UNAUTHENTICATED` in the exact envelope, `POST /pilot-training/_clock/set-current-utc` as SystemAdmin returned `{"current_utc": "2026-08-01T00:00:00.000Z"}`; process then killed cleanly. Two functional suites (78 + 58 assertions covering the full applicant pipeline, OCC staleness, seat gate, dual projections, billing/reversals, remediation loop, currency warning/lapse/requalify, medical grounding/restore, bid award ranking, scan counters, RBAC identity checks, and fresh-boot store emptiness) both pass with zero failures.

## Step 7: Run Tests and Iterate — 2026-08-14T04:35:00.000Z

All 8 parallel rounds pass 81/81 with zero failures and zero errors. The loop exits here.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (648 test executions per sweep).
- Sweep 1: 79/81 in every round — 2 deterministic failures (identical pair in all 8 rounds; interim "flaky" FAILED lines in the raw log were cross-round stdout interleaving artifacts, not real flakiness — the results files were uniform).
- Sweep 2: **81/81 × 8 rounds, all green.**

**Tests deleted:** none.

**Fixes applied to `test_suite/` (2):**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/test_suite/test_01_applicants_screening_records.py` — `TestClearGate::test_clear_with_unverified_records_returns_records_incomplete`: the setup left the applicant in `PRIA_PENDING`, so the clear attempt hit the PRD §2.8 priority-4 from-state guard (`ERR_APPLICANT_INVALID_STATE`) before the priority-9 records gate the test asserted (`ERR_RECORDS_INCOMPLETE`). PRD §3.1 declares clear as `PRIA_VERIFIED → CLEARED`, so the records gate is only observable from `PRIA_VERIFIED`. Fixed the setup to verify the PRIA request (bubbling the applicant to `PRIA_VERIFIED`), then open a fresh `DRAFT` DRUG_TEST request so the file is incomplete again — the records gate now fires uniquely. Removed the now-obsolete `_drive_to_pria_pending_with_sent_request` helper method.
2. `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/test_suite/test_02_classes_seats_and_occ.py` — `TestConfirmWithdrawSeatInvariant::test_counter_identity_holds_at_each_step`: baseline asserted `active_enrollment_count == 1` while the setup leaves en1 CONFIRMED + en2 TENTATIVE; PRD §3.2 counts TENTATIVE as active, so the PRD-derived value is 2 (the sibling test in the same class already asserts exactly that and passed). Replaced the mis-derived baseline and the trailing `post == base` comparisons with PRD-derived absolute counters at each step (1/2 → 2/2 → 1/1), preserving the confirm+withdraw conservation intent of the design instance.

**Fixes applied to `test_helpers/`:** none — fixtures/factories were PRD-faithful; both bugs lived in the test functions' setup/assertions.

**Fixes applied to `implementation/`:** none — the implementation was PRD-correct on both failure paths (from-state guard precedence per §2.8; counter semantics per §3.2).

**Operational note:** the first sweep-2 launch was destroyed by a self-matching `pkill -f` in the launcher command plus a wrapper timeout; the sweep was relaunched detached via `setsid` and ran to completion. No test or implementation impact.

## Step 8: Finalize PRD — 2026-08-14T04:40:00.000Z

**Both step_7_diff items are pure test bugs with zero PRD silence.** The implementation was PRD-correct at both failure sites, and the PRD already uniquely determines both behaviors. `PRD_FINALIZED.md` is byte-identical to `PRD.md` (verified: same md5 `18852ed9b8beda9a02d8f587d25e9384`).

**Line counts / delta:** PRD.md = 336 lines, PRD_FINALIZED.md = 336 lines, 0% delta.

**Changes:** none.

**Per-item investigation log (pre-edit search for the two candidate edits, both rejected):**

- **Candidate edit 1 — clear-gate error precedence (step_7_diff item 1)**
  - (a) Subject: ordering of the from-state guard vs. the records-completeness gate on `POST /applicants/{id}/clear`.
  - (b) Paths enumerated: `implementation/routes/applicants.py:96-116` (clear endpoint: role check → `get_applicant` → `status != "PRIA_VERIFIED"` → `ERR_APPLICANT_INVALID_STATE` → all-requests-`VERIFIED` + ≥1 `PRIA` → `ERR_RECORDS_INCOMPLETE` → `has_valid_first_medical` → `ERR_NO_VALID_MEDICAL` → seniority assign); `implementation/services.py:633-637` (`has_valid_first_medical`: `cert_class == "FIRST" and status == "VALID"`); plus the bubble-up writer that produces `PRIA_VERIFIED` (records-request verify cascade) to confirm the only reachable clear-from states. PRD cross-refs: §2.8 priority list — "(4) entity from-state guards … (9) the two clear-gate referential checks, records completeness before medical validity"; §3.1 — clear declared as `PRIA_VERIFIED → CLEARED` with checks "in a fixed order: first … records … then a valid first-class medical". The test bug was setup-only (applicant left in `PRIA_PENDING`, so priority-4 legitimately masked priority-9). PRD already uniquely determines the observed behavior in both directions (no impl choice left open, no impl/PRD divergence, including the empty-file case: `not requests` → `ERR_RECORDS_INCOMPLETE`, which the PRD's "at least one PRIA request present" clause already forces).
  - (c) No wording committed — no edit warranted.

- **Candidate edit 2 — `active_enrollment_count` / `confirmed_count` set membership (step_7_diff item 2)**
  - (a) Subject: which enrollment statuses count toward the class's derived seat counters.
  - (b) Paths enumerated: `implementation/services.py:39-40` (`ACTIVE_ENROLLMENT_STATES = {"TENTATIVE","CONFIRMED","IN_PROGRESS","REMEDIATION"}`, `CONFIRMED_ENROLLMENT_STATES = {"CONFIRMED","IN_PROGRESS","REMEDIATION","COMPLETED"}`); `services.py:416-445` (`recompute_class`: counts → floor(cap×(1+rate)) → aggregate floor → per-phase walk half-up → `over_committed = active > max_seats_sellable`); serializer exposure at `services.py:136-137`; all `recompute_class` callers (class read/list, enrollment create/confirm/start/withdraw/disqualify/retrain/resume, seat-parameter PATCH) share the same sets — no divergent path exists. PRD §3.2 states the two sets verbatim ("`active_enrollment_count` counts enrollments in `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION`, while `confirmed_count` counts enrollments in `CONFIRMED`, `IN_PROGRESS`, `REMEDIATION`, or `COMPLETED`") — the test's baseline assertion of 1 against a CONFIRMED+TENTATIVE setup contradicted the PRD itself; the sibling test asserting 2 passed from the start.
  - (c) No wording committed — no edit warranted.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/workspace/PRD_FINALIZED.md` (byte-identical copy of `PRD.md`).

## Step 9: PRD Completeness Scan — 2026-08-14T04:50:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1621_airline_pilot_recruitment_training_records/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (byte-identical to `PRD.md`), aligning the PRD to `implementation/` (the alignment target).

**Source vs. output:** PRD_FINALIZED.md = 336 lines / 56,799 chars → PRD_COMPLETED.md = 338 lines / 64,074 chars; char-delta +7,275. No new sections added; all changes are in-paragraph inserts/revisions (one insert spans two lines, hence +2 lines).

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions (24 edited passages total).

**Changes** (section — insert/revise — ambiguity/mismatch — what changed — impl evidence):

- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is rendered from the logical clock, not wall clock — util.py:49,61,77
- §2.2 — insert — ambiguity — unmatched path/method → `ERR_RESOURCE_NOT_FOUND` (404); absent body treated as `{}`; non-JSON/non-object body → `ERR_INVALID_REQUEST` — app.py:36-49, util.py:85-95
- §2.3 — revise — ambiguity — pagination param validation errors (`ERR_INVALID_REQUEST` for non-integer/out-of-range limit/offset), `has_more` formula (`offset + returned rows < total_count`), `created_at` tie-break by insertion sequence — util.py:143-172
- §2.4 — revise — ambiguity — scan counter semantics (increment only on actual transition, incl. each LAPSED→EXPIRED promotion); scan transitions are version-less system transitions except auto bid-period close which bumps `version` — ops.py:22-84
- §3.1 — revise — ambiguity+mismatch — applicant field shapes (non-empty strings, integer `total_flight_hours`); email rule relaxed from "RFC-5322" to impl's actual check (single `@`, dotted domain, no whitespace) with `ERR_INVALID_REQUEST` for malformed — applicants.py:30-37, util.py:140
- §3.1 — revise — ambiguity — records-request create: invalid `request_type` → `ERR_INVALID_REQUEST`; receive validates payload after the from-state guard; `RECEIVED` outcome leaves `failure_reason` null — applicants.py:190-192, 247-262
- §3.1 — revise — mismatch — reject's optional `reason` is accepted but **not persisted** (PRD said "recording an optional reason") — applicants.py:122
- §3.1 — revise — ambiguity — applicant-withdrawal cascade expires DRAFT/SENT requests with `updated_at` refresh and no version bump — applicants.py:153-158
- §3.2 — revise — mismatch — equipment `code` uniqueness dropped (impl enforces none); numeric fields must be integers, `ERR_INVALID_REQUEST` otherwise — classes.py:26-49
- §3.2 — revise — ambiguity — class-cancellation Link 1 enrollment withdrawals are version-less system transitions — classes.py:183-197
- §3.3 — revise — ambiguity — enrollment-create gate order: `expected_training_class_version` presence/shape (`ERR_INVALID_REQUEST`) checked after class-OPEN and before duplicate check; new enrollment starts with `current_phase` `GROUND_SCHOOL` — classes.py:241-268
- §3.3 — revise — ambiguity — withdrawal event-cancellation is version-less; resume recomputes the class forecast without incrementing class `version` — classes.py:349-355, 404-410
- §3.4 — revise — ambiguity — instructor create validation errors; slot `end_at > start_at` violation → `ERR_INVALID_REQUEST`; simulator-slot list filters `equipment_id`/`status` — resources.py:27-45, 69-103
- §3.4 — revise — ambiguity — events may be scheduled only for IN_PROGRESS/REMEDIATION enrollments (any other state → `ERR_PHASE_PREREQUISITE_NOT_MET`) — events.py:124-126
- §3.4 — revise — ambiguity — complete requires integer score 0-100 (`ERR_INVALID_REQUEST`); fail's optional score same shape; CheckAirman may complete/fail only events they instruct (`ERR_FORBIDDEN_ROLE`) — events.py:172-188, 210-212, 240-246
- §3.5 — revise — mismatch — checkride-scheduling gate order re-sequenced to impl/§2.8 band order (state → SoD → tier → window → ride_type shape); invalid `ride_type` → `ERR_INVALID_REQUEST` — events.py:288-305
- §3.5 — revise — ambiguity — record-outcome: outcome enum validated last (constraint band) after the medical gate — events.py:367-376
- §3.5 — revise — ambiguity — PASS: phase advance and existing-qualification `operating_state` refresh are version-less touches; upsert-created qualification also gets `operating_state` `ACTIVE`; PASS leaves a REMEDIATION enrollment in REMEDIATION — events.py:386-410
- §3.5 — revise — ambiguity — FAIL while already in REMEDIATION: no re-entry, original `entered_remediation_at` kept, no second RETRAINING surcharge; FAIL cascade enrollment transition is version-less — events.py:413-431
- §3.6 — revise — ambiguity — flight-activity field types (integer `landings`, number `hours`); qualification read recomputes counters without touching `last_evaluated_at`/`updated_at`; flight-activity list filters by `qualification_id` — quals.py:80-85, 165-206
- §3.6 — revise — ambiguity — currency transitions only out of QUALIFIED/CURRENCY_WARNING; LAPSED/REQUALIFYING evaluations refresh counters without state change; refresh-currency bumps `version` only on an actual transition — quals.py:88-95, services.py:569-594
- §3.6 — revise — ambiguity — requalify evidence measured by event `updated_at` in (now−30d, now]; certify requires `completed_at` at or after the requalification transition — quals.py:107-151
- §3.6 — revise — ambiguity — medical create validation errors; through-dates computed for every cert class; scan skips SUSPENDED/EXPIRED certs; DOWNGRADED never returns to VALID even if the clock moves backwards — quals.py:217-244, ops.py:36-43
- §3.6 — revise — mismatch — grounding cascade fires only when no other VALID first-class certificate remains; cascade/restoration transitions are version-less; suspending a non-VALID certificate → `ERR_INVALID_REQUEST` (400) — services.py:655-670, quals.py:273-280
- §3.7 — revise — ambiguity — bid-period create validation errors (`ERR_INVALID_REQUEST`) — bids.py:35-38
- §3.7 — revise — ambiguity — `preference_rank` must be an integer ≥ 1; duplicate-bid check spans all bid states (re-bid after withdrawal still `ERR_DUPLICATE_BID`); period-not-OPEN on submission → `ERR_BID_PERIOD_INVALID_STATE`; withdrawal of a SUBMITTED bid whose period closed → `ERR_BID_PERIOD_INVALID_STATE`; null `seniority_snapshot` captured — bids.py:177-201, 229-244
- §3.7 — revise — ambiguity — award ranking: null snapshot sorts last, null `cleared_at` sorts last; award-driven bid transitions refresh `updated_at` without bumping bid `version` — bids.py:122-153
- §3.8 — revise — ambiguity — CHECKRIDE-phase training events bill the flat 120,000-cent `CHECKRIDE` entry — services.py:499-500
- §3.8 — revise — ambiguity — invalid `variant` query value → `ERR_INVALID_REQUEST` (400) — applicants.py:168-170

Pipeline complete. Final verification: 8/8 result files each report 81/81 passed, 0 failed, 0 errors.
