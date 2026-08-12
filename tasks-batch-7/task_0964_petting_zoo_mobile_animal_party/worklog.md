# Worklog — task_0964_petting_zoo_mobile_animal_party

## Step 1: Create task directory — 2026-08-10T02:17:29.489Z

Task directory `tasks/task_0964_petting_zoo_mobile_animal_party/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 treated as done (no auto-index scan run, per headless instructions). Difficulty parameter: "generate task hard than expert level!" — to be passed through to the scaffold generator at Step 2.

## Step 2: Generate scaffold — 2026-08-10T03:02:13.540Z

All three artifacts are generated, lint-clean, and on disk. Summary:

**`SCAFFOLD.yaml`** (§1.0–§1.7; no difficulty/corner keys)
- **14 entities**: Customer, Venue, Animal, HealthRecord, Handler, Booking (central, ~30 fields incl. computed quote/final/pricing/score fields), BookingAnimal, StaffAssignment, AddOnRequest, Permit, Waiver, InsuranceCertificate, WeatherAssessment, LedgerEntry — flat topology with FK joins
- **9 state machines**: Booking (12-state lifecycle with CONFIRMED↔WEATHER_HOLD cycle, three cancel variants, parallel payment_status dimension), Animal (AVAILABLE↔QUARANTINE cycle + retire cascade), BookingAnimal, StaffAssignment, AddOnRequest, Permit (DENIED→SUBMITTED re-application cycle), InsuranceCertificate, Waiver (compound, count-derived)
- **2 OCC concurrency rules**: reschedule + add-on attach, both on `Booking.version` → 412 ERR_STALE_BOOKING_VERSION
- **11 calculation rules**: dual-variant booking_price (provisional/final) and compliance_score (screening/audited); combinatorial travel_setup_fee (mode a), line_item_rounding with pinned round-per-line-then-sum (mode b), institutional discount/surcharge evaluation order (mode c); deposit half-up rounding; cancellation refund waterfall (3 variants); handwash/staff thresholds; handler 480-min daily capacity; animal buffered rest windows
- **33 ordered validation rules** (auth → schema → existence → state/OCC → safety → constraint → temporal → referential → fiscal), **41 error codes**, **54 endpoints**, **6 roles** with segregation-of-duties (permit submitter ≠ decider)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 20 instances: 2×dual_variant_calc (fiscal vs safety domains), 3×combinatorial_formula (modes a/b/c — e.g. pinned literals 34375/29637 divergence, 11532 vs 11533 rounding-order cent, 45890 vs 45889 evaluation-order cent), 2×non_linear_state_machine, 2×transitive_cascade (depth-3 health-FAIL quarantine chain, depth-2 cancel→release→minutes chain), 2×priority_pair_validation_conflict (state-vs-safety, constraint-vs-fiscal), 2×boundary_precision (handwash ceil boundary, exact 72.0h refund tier), 3×cross_entity_state_dependency, 2×resource_temporal_overlap (buffered intervals vs aggregate daily capacity), 2×compensating_invariant (money 5181=2681+2500; handler minutes 0→120→0)

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 53 entries: 45 active (entities, state machines, calculations, validations incl. SoD/lead-time/stale-assessment/quote-stale/score-gate corners, endpoints, RBAC, OCC + derived-field cross-cutting, immediate consistency) + 8 `excluded_because` stubs citing difficulty instances

**Verification**: all arithmetic literals were pre-computed in Python (weekday checks, tier boundaries, half-up rounding) before being pinned into asserts; `scaffold_lint.py` verdict: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. §1.5 endpoints declared: 54 · §1.1 entities: 14 · §1.8 instances: 20 · §1.9 instances: 45 · calls scanned: 679

## Step 3: Copy shared files — 2026-08-10T03:02:32.343Z

Copied `./INSTRUCTION.md` to `tasks/task_0964_petting_zoo_mobile_animal_party/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T03:12:40.000Z

PRD generation complete and verified. `workspace/PRD.md` exists on disk (54,066 bytes, 349 lines).

Section structure:
- §1. Introduction (business context + system goals)
- §2. Global Specifications & System-Wide Principles (10 subsections): RBAC, API Response Structure, Pagination (limit default 10/min 1/max 100, offset 0, created_at ascending), Resource Identity/Timestamps/Versioning, Money/Precision/Rounding (integer cents, half-up), OCC on Bookings, Nested Paths/Existence Validation, Logical Clock (default 2026-05-01T00:00:00Z), Validation Pipeline and Gate Ordering, Booking Ledger
- §3. Business Logic & Workflows (8 subsections, lifecycle grouping)
- §4. Endpoint Definitions: all 54 endpoints
- §5. Error Code Catalogue: all 41 errors

Coverage notes: all 42 state-machine transitions expressed; all 11 calculations rendered as precise prose with pinned evaluation order and reconstructible constants (incl. 3343/3844/11532 vs 11533 rounding counterexample, deposit 30% 34375→10313 example, refund waterfall 168/72/24-hour inclusive boundaries, compliance score with both variants and the 60 confirm gate, 480-minute handler capacity, buffered rest-window half-open semantics); both OCC rules named with expected_booking_version/ERR_STALE_BOOKING_VERSION/412; all 33 validation priorities surfaced via §2.9 pipeline plus per-endpoint orderings.

Hard Contract Reports: field coverage PASS (94/94); rule coverage PASS (33 validations, 2 OCC, 42 transitions, 11 calculations, 54 side effects, 94 fields, sibling-branch symmetry); path purity PASS (533 backtick tokens scanned, 0 path/method leakage in §3).

Neither withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) was opened or referenced.

## Resume after SIGKILL — 2026-08-10T06:18:42.393Z

Headless run was SIGKILLed mid-flight. Disk measurement before resuming (nothing regenerated that was already complete):

- **Steps 1–4: COMPLETE** — SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/INSTRUCTION.md, workspace/PRD.md (54,066 bytes) all present; worklog entries above confirm clean completion.
- **Step 5: INCOMPLETE** — test_helpers/ has all 9 expected files (types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__), but test_suite/ holds only conftest.py + test_01_quote_pricing.py against 20 §1.8 difficulty instances + 45 §1.9 corner instances. Test generation was killed after its first file. Step 5 will be re-run to complete the suite; existing complete files are kept.
- **Step 6: COMPLETE (verified)** — implementation/ registers exactly the 54 (method, path) pairs SCAFFOLD.yaml §1.5 declares (normalized diff: identical). `import app` OK; all 7 blueprints registered; `bash start.sh` boots and answers GET /petting-zoo/animals and POST /petting-zoo/_clock/set_current_utc with correct envelopes. Kept as-is.
- **Steps 7–9: NOT STARTED** — no results.*.json, no PRD_FINALIZED.md, no PRD_COMPLETED.md.

Resuming at Step 5 (test-suite completion), synchronously per headless constraints.

## Step 5: Generate unit tests (resumed completion) — 2026-08-10T06:35:00.000Z

**Pre-existing files kept as-is (no repairs needed)**
- All 9 `test_helpers/` files (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) — inspected; complete and conformant with the skill spec (full endpoint coverage in `ApiClient`, correct immutable-record TypedDicts, error map registered with the framework, entity-backed Customer identity threading via `make_customer_headers`, composite fixtures for the goat/sheep/2-animal/3-animal scenarios).
- `test_suite/conftest.py` and `test_suite/test_01_quote_pricing.py` (12 tests) — complete and conformant; covers `Difficulty/combinatorial_formula/{travel_fee_multi_input_nonlinear, invoice_per_line_rounding_order, discount_surcharge_evaluation_order}` (2 tests each) plus corner instances `guest_surcharge_tier_boundary_50_vs_51`, `deposit_rounds_half_up`, `reptile_addon_adds_dedicated_handwash_station`, `quote_reconcile_after_addon_approval`, `booking_create_computed_field_input_ignored`. One note: its `test_requote_reconciles_after_addon_approval` asserts 28600 (PRD-formula-correct: 20000 subtotal + 600 surcharge + 8000 travel), not the corner yaml's pre-computed 28840 — the test follows the PRD, which is authoritative.

**New test files created (74 tests)**
- `test_02_dual_variant_pricing_and_scoring.py` — 4 tests
- `test_03_state_machine_cycles.py` — 4 tests
- `test_04_cascades.py` — 4 tests
- `test_05_dispatch_gate_order.py` — 4 tests
- `test_06_boundary_precision.py` — 4 tests
- `test_07_cross_entity_gates.py` — 6 tests
- `test_08_resource_temporal_overlap.py` — 4 tests
- `test_09_compensating_invariants.py` — 4 tests
- `test_10_entities_and_reads.py` — 8 tests
- `test_11_booking_state_and_waiver.py` — 5 tests
- `test_12_creation_and_attach_validations.py` — 9 tests
- `test_13_permits_weather_occ.py` — 6 tests
- `test_14_confirm_dispatch_rejections.py` — 8 tests
- `test_15_rbac.py` — 4 tests

**Total coverage (audited programmatically)**
- §1.8 difficulty: **20/20 instances covered, each with exactly 2 tests** (40 tests). 0 skipped — every instance passed the PRD-first two-condition filter.
- §1.9 corner: **45/45 non-stub instances covered, ≥1 test each** (46 tests). 0 instances skipped outright; the 8 `excluded_because:` stubs were not translated and their difficulty-instance cross-references all resolve.
- Whole suite: 86 tests, `pytest --collect-only` clean, no skip/xfail markers, no scaffold references.
- Citation pass: all docstring PRD quotes verified verbatim against `workspace/PRD.md` (whitespace-normalized substring check, 0 failures after fixing 12 markdown-label quotes to include PRD's literal `**Link N:**` / `**State validity**` —` / `**Request shape**` —` / `**Aggregate capacity:**` formatting). Every docstring ends with exactly one resolving `Design:` tag.

**Assertion-level weakenings (instances still emitted; only the non-uniquely-derivable sub-claim dropped)**
- `Corner/state_machines/payment_creates_ledger_side_effect`: dropped `payment_status == UNPAID` after a 1000c partial payment — PRD §3.6 "advances payment_status: from UNPAID to DEPOSIT_PAID on the first payment" is ambiguous about whether any first payment or only a deposit-reaching payment flips the status. Kept the derivable claims (PAYMENT entry type/amount, `total_paid_cents` recompute).
- `Corner/entities/customer_creation_applies_defaults`: dropped `created_at == updated_at` equality — PRD §2.4 never states they are equal at creation. Kept version==1, envelope shape, echoed fields, and ISO-8601 presence/format for both timestamps.
- `Difficulty/cross_entity_state_dependency/booking_animal_confirm_requires_valid_health_cert`: cert-expiry asserted as `startswith("2026-07-01")` rather than exact-string equality, since PRD does not pin the datetime serialization format.

## Step 6: Generate implementation — 2026-08-10T06:33:00.000Z

Implementation was generated by the interrupted run and verified complete during resume (see "Resume after SIGKILL" entry): 54/54 (method, path) route pairs match SCAFFOLD.yaml §1.5 exactly (normalized diff: identical), `import app` clean, all 7 blueprints registered, `bash start.sh` boots and serves correct envelopes. Kept as-is; no regeneration.

## Step 7: Run tests and iterate — 2026-08-10T06:55:30.000Z

Clean 8-round parallel sweep achieved: 86/86 passed in every round, 0 failed, 0 errors.

- **Iterations run:** 2 (iteration 1: 17 deterministic failures identical across all 8 rounds; iteration 2 after fixes: 8/8 rounds fully green).

- **Tests deleted:** None. Every failing test traced to a verbatim PRD rule (§3.3 handler capacity/minutes accounting, §3.7 weather-cancel refund waterfall); no PRD-silence or unique-derivability collapse found.

- **Fixes applied to `test_helpers/`:** None — the fixtures were PRD-faithful.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_09_compensating_invariants.py` — module-level helper `_setup_weather_held_sheep_with_permit()` referenced the pytest-injected `api` fixture outside any test function (`NameError: name 'api' is not defined`, 2 tests). Fix: added an `api` parameter to the helper and passed the fixture at both call sites, matching the file's own idiom used everywhere else.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/services/cascade.py` — `handler_overbooked()` referenced `DAILY_CAPACITY_MINUTES` without importing it (`NameError` → HTTP 500 on every POST `/petting-zoo/bookings/{id}/staff-assignments`, 15 tests failing in setup). Fix: added `DAILY_CAPACITY_MINUTES` to the existing `from services.pricing import (...)` block. Verified locally against a booted server: assignment creation returns 201 and `scheduled_minutes_total` correctly reports the 120-minute event duration, per PRD §3.3 ("the sum of the existing event durations plus the new event's duration must not exceed 480 minutes").

- **Verification:** fixes confirmed by reproduction (traceback captured pre-fix, 201 + correct handler total post-fix), then the full foreground `sweep.sh` run: rounds 1-8 all report `passed=86 total=86`.

(Process note: the Step-7 loop subagent's first backgrounded sweep died with its turn; the orchestrator re-ran `sweep.sh` from its own shell, then resumed the same subagent — context preserved — which diagnosed, fixed, and re-swept to green in the foreground.)

## Step 8: Finalize PRD — 2026-08-10T06:58:00.000Z

Done. `workspace/PRD_FINALIZED.md` written.

**Line counts / delta:** PRD.md 349 lines → PRD_FINALIZED.md 349 lines (one in-place sentence revision on line 156; 0% line-count delta, one line's text changed).

**Changes:**
- §3.3 (Handlers, Certifications, and Daily Capacity) — revise — the capacity-guard scope sentence now excludes the new booking's own assignments from the guards' comparison set ("whose parent booking is non-terminal, **is not the new booking itself**, and shares the new booking's calendar date in UTC — a booking's own assignments are never weighed against it, so assigning the same handler to the same booking more than once does not, by itself, trip either guard") — `implementation/services/cascade.py:195` (`if sa["booking_id"] == booking["id"]: continue` inside `handler_overbooked`).

**Why only one edit:** Of the two step_7_diff items, the `test_09` helper fix was pure test mechanics (no PRD semantics), and the `cascade.py` import fix was a pure crash fix over behavior PRD §3.3 already pins. The audit of the verify questions Step 7 raised found: (1) `scheduled_minutes_total` response-visibility is already pinned by §3.3's first paragraph and the §2.6 endpoint table (line 265), and the POST staff-assignments response correctly returns the assignment, not the handler — no patch; (2) "event durations, in minutes" is uniquely derivable as `end_time − start_time` from the §3.4 window definition — no patch; (3) the derived total's state filter (`ASSIGNED` only, no booking-state filter) matches `recompute_handler_minutes` exactly as PRD already states — no patch. The one genuine gap was the guard comparison set: PRD's literal wording sweeps same-booking assignments in (a second assignment of the same handler to the same booking shares the date and strictly overlaps the identical window → literal reading rejects with `ERR_HANDLER_OVERBOOKED`), while the impl skips them and allows the duplicate. Unlike the parallel animal/add-on cases, no duplicate-assignment rejection error exists in the PRD error catalog or `errors.py`, so the exclusion is a real behavioral choice the impl pinned and the PRD left ambiguous — and it sits on the exact path Step 7 surfaced.

**Pre-edit search log (edit 1):**
- (a) Subject: scope of the §3.3 handler capacity guards — which existing assignments the strict-overlap and aggregate-capacity guards consider, specifically whether assignments on the new booking itself are included.
- (b) Impl paths enumerated and read/grepped: `services/cascade.py:182-206` (`handler_overbooked` — skips `sa["booking_id"] == booking["id"]` and `exclude_booking_id`); both callsites — `routes/booking_children.py:165-191` (create, no exclude → same-booking skip is what permits duplicate handler assignments) and `routes/bookings.py:302-355` (reschedule, `exclude_booking_id=booking["id"]` → own assignments are re-check candidates but excluded from the comparison set); `errors.py` (grep: no duplicate-assignment error exists); PRD-wide grep for `ERR_HANDLER_OVERBOOKED` / guard references (only §3.3 line 156 definition and §3.5 line 224 reschedule re-run — wording confirmed consistent with both, since in reschedule "the new booking" is the booking being rescheduled and comparing it against itself would be vacuous); all `recompute_handler_minutes` callsites (cascade.py:65 cancel cascade, bookings.py:354 reschedule, bookings.py:500 completion sweep, booking_children.py:190/207 create/release) confirmed unrelated to guard scope.
- (c) Wording adjustment: added the predicate "is not the new booking itself" inline in the existing enumeration (rather than as a separate rule) so the reschedule re-run path in §3.5 inherits the same comparison-set definition, and scoped the consequence clause with "does not, by itself, trip either guard" to avoid implying unconditional success (terminal-booking and other checks still apply).

## Step 9: Complete PRD — 2026-08-10T07:00:14.342Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` 349 lines / 54264 chars → `PRD_COMPLETED.md` 349 lines / 57870 chars (+3606 chars, 19 lines revised in place, 0 lines added/removed — all changes are inline paragraph inserts/revisions, no new sections).

**Counts:** 19 changes total — 17 ambiguity-pins, 2 mismatch-revisions (the handwash reptile-station scope and the §2.9 authorization-vs-existence ordering, where the PRD's literal text contradicted or cut against the implemented behavior).

One bullet per change (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl file:line}`):

- §2.1 — insert — ambiguity — unregistered-`Customer` `X-User-ID` rejected with ERR_FORBIDDEN at the authorization layer — implementation/middleware.py:23-25
- §2.3 — revise — ambiguity — non-integer limit/offset → ERR_INVALID_REQUEST; out-of-range values clamped (limit→[1,100], offset→0), not rejected; created_at ties broken by id ascending — implementation/util.py:165-193
- §2.9 — revise — mismatch — entity-backed ownership checks that require loading the resource run after it resolves (404 before ownership-403); path-id comparisons may run before existence — implementation/routes/bookings.py:163-165 vs customers.py:74-76
- §3.1 — insert — ambiguity — duplicate email → ERR_INVALID_REQUEST — implementation/routes/customers.py:39-40
- §3.1 — insert — ambiguity — Customer fetch of customer record and venue list restricted to own id (ERR_FORBIDDEN otherwise) — implementation/routes/customers.py:50-51,58-59
- §3.2 — revise — ambiguity — health-record `valid_until` is optional (null when omitted) — implementation/routes/animals.py:97
- §3.2 — insert — ambiguity — FAIL on an already-QUARANTINE animal leaves status unchanged and re-runs a no-op cascade — implementation/routes/animals.py:119-124
- §3.3 — insert — ambiguity — staff assignment rejected with ERR_INVALID_STATE only from terminal booking states — implementation/routes/booking_children.py:175-176
- §3.4 — insert — ambiguity — booking `customer_id` from X-User-ID header, never body — implementation/routes/bookings.py:94
- §3.4 — insert — ambiguity — all computed quote/event-day fields null until the transition that computes them — implementation/routes/bookings.py:105-120
- §3.4 — insert — ambiguity — Customer list-bookings sees only own rows; foreign `customer_id` filter → ERR_FORBIDDEN — implementation/routes/bookings.py:142-147
- §3.4 — insert — ambiguity — roster attach rejected with ERR_INVALID_STATE only from terminal booking states — implementation/routes/booking_children.py:83-84
- §3.4 — insert — ambiguity — add-on `duration_minutes` ≥ 1; request from terminal booking → ERR_INVALID_STATE; denial_reason optional (null default); denial does not clear quote_fresh or bump booking version — implementation/routes/booking_children.py:230-235,264,290-293
- §3.4 — revise — mismatch — reptile-show +1 handwash station applies even when the venue flag is false (base requirement zero) — implementation/services/pricing.py:87-91
- §3.5 — insert — ambiguity — permit creation carries no booking-state gate — implementation/routes/booking_children.py:311-330
- §3.5 — revise — ambiguity — permit denial_reason optional (null when omitted) — implementation/routes/permits.py:44
- §3.6 — insert — ambiguity — payment `amount_cents` integer ≥ 1; response is 201 carrying the created PAYMENT ledger entry; payments do not increment booking version — implementation/routes/bookings.py:211-227
- §3.6 — insert — ambiguity — waiver-signature batch `count` ≥ 1 — implementation/routes/booking_children.py:351
- §3.7 — insert — ambiguity — unknown/foreign `weather_assessment_id` → ERR_INVALID_REQUEST — implementation/routes/bookings.py:404-406
- §3.7 — insert — ambiguity — `new_end_time` strictly after `new_start_time` enforced at shape layer; successful reschedule recomputes `scheduled_minutes_total` of handlers with ASSIGNED assignments — implementation/routes/bookings.py:309-310,352-354
- §3.7 — insert — ambiguity — cancellation ledger append order pinned: REFUND, then FORFEIT, then PENALTY last — implementation/services/cascade.py:106-115
- §3.8 — insert — ambiguity — finalize-invoice when paid < final_total: no further ledger entry, payment_status unchanged — implementation/routes/bookings.py:517-522

All other implementation behaviors (pricing 8-step order, rounding points, confirm 9-gate order, quarantine/retire/cancel cascades, OCC endpoints, error catalogue, endpoint role table, envelope shapes, clock semantics) were verified to already be pinned uniquely by the PRD and were left unchanged.
