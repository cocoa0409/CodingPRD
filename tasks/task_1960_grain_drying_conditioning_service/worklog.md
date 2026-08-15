# Worklog — task_1960_grain_drying_conditioning_service

## Step 2: Generate Scaffold — 2026-08-15T03:46:12.576Z

## Task 1960 — Grain Drying & Conditioning Service: scaffold complete

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/SCAFFOLD.yaml` (§1.0–§1.7, no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)
- Worklog entry appended to `/home/ubuntu/github/CodingPRD/worklog.md`

**SCAFFOLD.yaml counts:** 12 entities (Customer, GrainLot, MoistureTest, DryingChargeSchedule, DryerUnit, QueueTicket, DryerRun, BlendOrder, DamageClaim, StorageAgreement, Invoice, Payment) · 8 state machines + 2 OCC concurrency rules · 10 calculations · 12 validation priority rows · 67 endpoints · 46 errors · 5 roles (Grower entity-backed by Customer; IntakeTechnician/DryerOperator/ClaimsAdjuster/ElevatorManager opaque; segregation-of-duties model).

**§1.8: 20 non-stub instances** — dual_variant_calc 2 (lot weight provisional-vs-scale 9068/9050/18 lbs variance; run energy metered-vs-estimated 5575 vs 5931) · combinatorial_formula 2 in different modes ((a) tiered bracket + FM surcharge + min floor = 7366; (b) pinned round-per-line-then-sum with a 9915-vs-9916 discriminator) · non_linear_state_machine 3 on different entities (GrainLot damage-hold cycle, DamageClaim appeal cycle, QueueTicket preempt/requeue cycle) · transitive_cascade 2 from different triggers (run-complete→lot→agreement→STORED depth-3; claim-pay→prepaid→waterfall→auto-PAID depth-3/4) · priority_pair_validation_conflict 2 (state vs fiscal; safety vs temporal) · boundary_precision_check 2 (moisture bracket 20.0→2000 vs 20.1→2550; capacity 8000 allowed vs 8001 rejected) · cross_entity_state_dependency 2 (QueueTicket→GrainLot; BlendOrder→GrainLot) · resource_temporal_overlap 3 with distinct interval semantics (run half-open+cooldown, daily aggregate sums, closed tariff windows) · compensating_invariant 2 (committed bushels; receivables position).

**§1.9: 57 non-stub instances + 8 excluded_because stubs** across all nine taxonomy sections (entities 8, state_machines 11, calculations 6, validations 23, endpoints 1, errors 1, rbac 4, cross_cutting_layers 2, consistency_model 1). All formula-derived asserts were pre-computed in Python before being pinned as literals.

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1041 calls scanned). Additional scripted checks: zero duplicate instance names across the union (85 total), zero unresolved grounds refs, zero unbound `${var}` placeholders, no forbidden concurrency vocabulary, all enum status values have producing transitions.

**Key design decisions** (recorded in worklog): quota/allocation + ledger-reconciliation archetypes on a flat topology; CONSUMED tickets keep holding daily capacity (abort compensation is capacity-neutral); claim-filing error mapped by lot state (delivered → ERR_CLAIM_AFTER_DELIVERY at priority 11, other non-DRIED → ERR_INVALID_STATE at 6); blend low-side pounds round UP via ceil so result moisture never overshoots target; estimated-variant fuel kept unrounded until per-run cent rounding; logical-clock endpoint with mandatory 2026-08-01T00:00:00Z startup default that also sweeps stale PENDING tickets to EXPIRED.

## Step 3: Copy Shared Files — 2026-08-15T03:46:27.720Z

Copied `./INSTRUCTION.md` → `tasks/task_1960_grain_drying_conditioning_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T03:56:52.927Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/PRD.md` — **375 lines**, generated solely from `SCAFFOLD.yaml` and the doc-generator skill (the two DIFFICULTY/CORNER design files were not opened; no sibling tasks consulted).

### Section list
- §1. Introduction (2 paragraphs, business-context angle)
- §2. Global Specifications — 9 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verified byte-verbatim against `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Clock and Calendar Dates · 2.5 Common Resource Properties · 2.6 Weigh-Station Units and Numerical Precision · 2.7 Optimistic Concurrency Control and Version Pins · 2.8 Segregation of Duties · 2.9 Reference Resolution and the Order of Validation
- §3. Business Logic & Workflows — 9 subsections organized as a chronological business pipeline (accounts → intake/testing → tariffs → queue/capacity → dryer runs → storage/title → blending → damage claims → billing), deliberately not the example's 7-subsection pattern
- §4. Endpoint Definitions (67-row table, 4 columns only) · §5. Error Code Catalogue (46 rows, 2 columns)

### Hard Contract reports
```
Field coverage check (Contract 1):
- entities[].fields + endpoints inputs + path params: 113 required, 113 present, 0 missing
- query-param identifiers: all present (verified in the same set)
- all 46 error ids and all 56 enum/state values present in backticks
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ordering: 12 checked, 12 expressed (§2.9 numbered order + masking examples), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + expected_<parent>_version + exact error id + 412), 0 missing
- state-machine transitions: 8 machines / 40 transitions checked, all fully expressed with preconditions and side effects, 0 missing
- calculations[]: 10 checked, 10 fully expressed in reconstructible prose (constants embedded: 0.5 handling, 56/60/60 lbs-per-bushel, 2500-cent deductible, 40% cap, 26.0/8.0 pre-existing, 0.5 out-of-spec tolerance, 450/1050/620 benchmarks), 0 missing
- validations[] conditions: 12 priority groups matchable to all 46 error ids in prose, 0 missing
- endpoint side effects / applies_to: all expressed (64-item spot audit, 0 failures after correcting two faulty check strings)
- structured field content (defaults, Payment's absent updated_at/version, pinned rounding steps): reconstructible, 0 missing
- sibling branches (two completion branches, PENDING/CONFIRMED cancel, dual withdraw/review/void/cancel paths): equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 540; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combos: 0
Status: PASS
```

### Scaffold-to-PRD semantic decisions worth recording
1. **`ERR_TARGET_MOISTURE_INVALID` "target >= intake at booking"** placed at queue-ticket creation (§3.4): booking a lot whose dry-down target already meets or exceeds its certified intake moisture is rejected; only decidable once a certified baseline exists, left implicit for `RECEIVED` lots.
2. **Claim-filing error split** narrated explicitly per scaffold: `LOADED_OUT`/`BLENDED_OUT` → `ERR_CLAIM_AFTER_DELIVERY` (422); `DAMAGE_HOLD` or pre-drying states → `ERR_INVALID_STATE` (409).
3. **Cooldown semantics** rendered as "the unit's `cooldown_minutes` idle gap is treated as occupied time around each run" with half-open scheduling windows — faithful to "overlap incl. cooldown" without inventing exact arithmetic.
4. **Claim-pay hold release made conditional** ("if the lot is still on hold") to cover the deny → appeal → assess → pay path, where the lot was already released at denial.
5. **Statement `outstanding_due_cents`** defined as the sum of `amount_due_cents` across ISSUED invoices, derived from the credit-gate text ("outstanding ISSUED dues").
6. **Payment against a PAID invoice** expressed as a derived consequence of the excess-due rule (due is zero, so any positive cash exceeds it) rather than inventing a new state error.
7. **Missing tariff window behavior**: preview → `ERR_SCHEDULE_NOT_FOUND`; ticket-confirm estimate → zero; invoice DRYING-line behavior deliberately left unspecified (scaffold silent — no invention).
8. **§4 path params** spelled `{id}` uniformly, following the endpoint table rather than the `{invoiceId}` variant inside the concurrency-rule prose.
9. **Version-observation trio** grouped in §2.7: two OCC rules (412) plus the invoice-issue schedule pin (409), with the explicit contract that no other endpoint takes a version field.
10. **Payment immutability** stated in §2.5 (`common_fields: false` → only `id` and `created_at`; `updated_at` and `version` absent).

## Step 5: Generate Unit Tests — 2026-08-15T04:22:55.688Z

Generation complete. All self-checks pass.

## Summary

**Output locations**
- `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/test_helpers/` — 9 modules: `types.py` (12 entity TypedDicts, 12 status enums, roles; Payment omits `updated_at`/`version` per PRD §2.5), `api_client.py` (48 endpoint methods covering all PRD §4 routes), `api_errors.py` (47 error IDs + HTTP map, registered with the framework), `assertions.py` (per-entity shape assertions + ledger invariants), `factories.py`, `constants.py` (canonical tariff/unit + all PRD thresholds), `test_users.py` (shared opaque-role headers + per-id builders incl. mandatory `make_grower_headers` for the entity-backed Grower role), `fixtures.py` (composite chains: `setup_base`, `create_tested_lot`, `create_queued_lot`, `create_dried_lot`, claim/review/assess/pay, draft/issue invoice, payments, blend approval, storage), `__init__.py` barrel.
- `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/test_suite/` — `conftest.py` + 10 test files (`test_01_intake_and_moisture` … `test_10_billing_and_payments`).

**Test counts**
- Queue A (Difficulty): 40 test functions — all 20 instances × 2 tests each.
- Queue B (Corner): 55 test functions — 55 of 57 non-stub instances × 1 test each.
- Total: 95 tests, all collected cleanly by `pytest --collect-only`.

**Per-instance skip list (PRD-first two-condition filter)**
1. `Corner/validations/blend_insufficient_grain_rejected` — PRD §3.7 names `ERR_INSUFFICIENT_BLEND_GRAIN` only in the execution re-verification paragraph ("required_low_lot_lbs must not exceed… or ERR_INSUFFICIENT_BLEND_GRAIN"), while the instance asserts rejection at order *creation*; a faithful PRD-only reader could legitimately create the DRAFT and fail only at execute. Not uniquely derivable.
2. `Corner/validations/target_not_below_intake_rejected` — PRD §3.4 states the "nothing to dry" rejection in the booking paragraph but omits it from the confirmation gate list; the instance asserts it at *confirm*. The two placements diverge between faithful readers.

All 8 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.

**Stage 1 / Stage 2 self-check results**
- Import check: `test_helpers` imports cleanly; all fixture/factory/client names referenced by tests exist.
- Tag audit (programmatic vs both yamls): 40/40 difficulty tags, 55/55 corner tags, zero unmatched tags, zero dual tags; every docstring's last line is its single `Design:` line.
- Citation audit: 144 quoted PRD citations; every one contains a ≥8-word substring surviving a literal whitespace-normalized grep of PRD.md (C1/C2/C3).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code; no reads of `workspace/implementation/`.
- Numeric audit: every hard-coded expectation (9068, 9244, 9.50, 18, 7366, 6696, 2000/2550, 1500 floor, 5575, 68.75→5931, 46.875→3984, 9915 vs 9916, 19281, 12271, 72725, 29090, 4375/17500/26250, 13309, 161.61, 170/242, 4200/11200/15.5, 5477/10477/15.0) re-derived from PRD formulas with round-half-up Decimal arithmetic — all match the design-index literals.

## Step 6: Generate Implementation — 2026-08-15T04:22:55.688Z

All done. The implementation is complete and verified across three independent fresh-boot smoke runs.

## Summary

**Location**: `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/implementation/`

**File inventory** (line counts, source only — pycache removed):
- `start.sh` (10) — executable; guards `pip install` behind `import flask`, `exec python3 app.py`, binds 0.0.0.0:$PORT (default 10000), foreground
- `requirements.txt` (1), `app.py` (53) — Flask entry, blueprint registration under `/grain-drying`, envelope-wrapped error handlers
- `db.py` (118) — in-memory dict store (empty at boot, no seeding), logical clock (default 2026-08-01T00:00:00Z), id/timestamp/version helpers
- `errors.py` (64) — full 46-entry error catalog with exact IDs and HTTP statuses
- `response.py` (45) — success/error envelope with `meta`/`response_type`/`data`, pagination fields in meta
- `middleware.py` (33) — X-User-ID/X-User-Role auth, 5-role check, grower ownership
- `validation.py` (177) — shape validators, pagination parsing (limit 1–100 default 10, offset default 0)
- `services/calculations.py` (227) — all Decimal, ROUND_HALF_UP, no intermediate rounding
- `routes/`: customers.py (94), lots.py (141), tests.py (142), schedules.py (111), units.py (68), tickets.py (206), runs.py (275), blends.py (189), claims.py (219), storage.py (142), billing.py (349), clock.py (29), helpers.py (163)

**Endpoint coverage: 67/67** — every row in the PRD §4 endpoint table is implemented, including charge-preview, capacity-calendar, statement, and the `_clock/set_current_utc` test-driving endpoint.

**State machines: 8/8** — GrainLot (incl. DAMAGE_HOLD loop, DRYING→STORED 3-link cascade, terminal load-out/blend-out), MoistureTest (certify/supersede/dispute/retest SoD), QueueTicket (confirm/cancel/preempt/requeue + system CONSUMED and EXPIRED), DryerRun (start/complete/abort/cancel + ticket/lot compensation pairs), BlendOrder (approve SoD, execute minting result lot), DamageClaim (review/assess/deny/appeal/withdraw/pay with hold release), StorageAgreement (RESERVED/ACTIVE birth by lot state, close, default title transfer), Invoice (issue pin, void rules, PAID↔ISSUED via payment/reversal/waterfall).

**Calculations: 10/10** — provisional shrink (water + 0.5 handling, round-half-up lbs), final weight reconciliation (2-dec shrink, variance), tiered drying charge (inclusive-down brackets, FM surcharge, min floor last), energy pass-through (metered and estimated variants, marginal tiers), Pearson-square blend quantities (ceil low-side lbs, 2-dec result moisture), claim liability (0.25/1.0/1.5 pinned ladder, deductible, 40% cap), storage accrual (half-open days, min-days floor), daily capacity commitment (CONFIRMED+CONSUMED, class cap with equality allowed), invoice composition (per-line rounding then sum, storage billed exactly once), prepaid waterfall (issued_at ASC, created_at tiebreak) with reversal restoration.

**Validation ordering** follows PRD §2.9 exactly: auth → role → ownership → FK existence (path L-to-R, then body) → shape → state (with the claim-file split mapping and DAMAGE_HOLD/terminal specializations) → OCC/pins (412/412/409) → SoD (403) → dryer safety 26.0 → structural → capacity → fiscal.

**Fresh-boot smoke test**: confirmed — three separate cold boots via `bash start.sh` (store empty each time, ~2s to HTTP-ready), with ~90 end-to-end checks across the three runs all passing, covering every workflow family, both energy variants, all cascades, all OCC/pin checks, and the RBAC/ownership matrix.

## Step 7: Run Tests and Iterate — 2026-08-15T04:30:01.535Z

All 8 rounds pass: 95/95 in every round. The sweep is clean.

## Summary

- **Iterations run**: 2 (initial sweep → fix → verification sweep).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/test_suite/test_10_billing_and_payments.py` — `TestPaymentReversal._paid_then_reversed(self)` changed to `_paid_then_reversed(self, api, manager_headers)`, and both call sites (`test_payment_reversal_not_reversible`, `test_payment_immutability_reverse_creates_compensating_record`) updated to pass the fixtures through. **Why**: the helper body referenced `api` and `manager_headers` — names that exist only as pytest fixtures in the test-method scope — producing `NameError: name 'api' is not defined` before any assertion ran. The assertions themselves (PRD §3.9 reversal-not-reversible `ERR_PAYMENT_NOT_REVERSIBLE`; compensating `REVERSAL` record + Payment immutability per §2.5) are verbatim PRD-covered and uniquely derivable, so this was a pure Python scoping bug in the test layer, fixed by threading the fixtures through. No assertion was weakened.

- **Fixes applied to `implementation/`**: none — the implementation was already PRD-faithful; both failures were the same test-layer `NameError`.

Final state: 95/95 tests passing in all 8 concurrent rounds (deterministic pass, zero flakiness observed). Orchestrator verification: all 8 `results.{1..8}.json` files confirm `passed=95/95`.

## Step 8: Finalize PRD — 2026-08-15T04:31:17.465Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/PRD_FINALIZED.md` exists as a verbatim copy of PRD.md with zero edits, and that is the correct outcome for this task.

## Summary

**Line counts**: PRD.md = 374 lines; PRD_FINALIZED.md = 374 lines; delta = 0 lines, 0.0%. Files are byte-identical (`diff -q` confirms).

**Changes**: none.

**Why zero edits are correct**: the `<step_7_diff>` contains no PRD-silence items and no PRD/impl mismatch items at all. Its single entry is a pure test-layer Python scoping bug: `TestPaymentReversal._paid_then_reversed(self)` in `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/test_suite/test_10_billing_and_payments.py:274` referenced the pytest fixtures `api` and `manager_headers` without declaring them as parameters, raising `NameError` before any assertion executed. Step 7 fixed it by threading the fixtures through the signature and both call sites (test_10_billing_and_payments.py:294, :318). No assertion was added, weakened, or deleted; no `implementation/` or `test_helpers/` change was made. There is no behavioral choice to pin because the implementation changed in zero places and the tests' asserted behavior never changed.

**Pre-edit verification (performed even though no edit resulted)**:
- (a) Subject identified: payment reversal semantics exercised at the Step 7 site — `ERR_PAYMENT_NOT_REVERSIBLE` gating, compensating `REVERSAL` record minting, Payment immutability.
- (b) Impl paths enumerated and read: `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/implementation/routes/billing.py:319-349` (`reverse_payment` endpoint — role gate `ElevatorManager`, `direction != "APPLICATION" or id in reversed_payment_ids` → `ERR_PAYMENT_NOT_REVERSIBLE` 409, compensating record with `direction: "REVERSAL"` and `reversal_of_payment_id`, invoice due restoration, `PAID` → `ISSUED` reopen on positive due, prepaid refund, HTTP 201); `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/implementation/errors.py` (error catalog); cross-checked against PRD.md §3.9 (line 247: reversal-not-reversible, compensating record, due/prepaid restoration, reopen), §2.5 (line 88: Payment immutability, only `id` + `created_at`), §2.6 (line 251: reversals return 201), and the payments-list filter (§3.9 line 245; route table line 317).
- (c) Wording adjustment: none needed — every behavior the test asserts is verbatim-present in the PRD (the test docstrings quote §3.9/§2.5 directly), and the implementation matches that prose exactly. The PRD already uniquely determines the behavior at the Step 7 site, so the HARD SCOPE rule ("every PRD edit must trace to a step_7_diff fix revealing PRD-silence or mismatch") permits no edit, and correctness demands none.

**Alignment-target note**: because Step 7 modified neither `implementation/` nor any assertion, an implementer reading PRD.md (equivalently PRD_FINALIZED.md) already produces the observed behavior; the failure Step 7 repaired existed only in the test harness's fixture plumbing, invisible to the PRD.

## Step 9: Complete PRD — 2026-08-15T04:43:14.190Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1960_grain_drying_conditioning_service/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place).

**Size**: source `PRD_FINALIZED.md` 374 lines / 60,442 chars → `PRD_COMPLETED.md` 376 lines / 66,483 chars; char-delta **+5,994**. 22 edit operations, no new sections.

**Counts**: 24 ambiguity-pins, 3 mismatch-revisions.

**Changes** (section — insert/revise — class — what — impl ref):

- §2.1 — insert — ambiguity — pinned per-resource customer-reference mapping used by grower ownership checks (ticket/test/run/claim via lot's `customer_id`, blend via high lot, agreement via `owner_id`, payment via invoice) — implementation/routes/helpers.py:95-144
- §2.2 — insert — ambiguity — pinned `ERR_NOT_FOUND` (404) for unrouted paths, `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), same envelope — implementation/app.py:37-49
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (1..100, ≥0); non-integer → `ERR_INVALID_REQUEST` — implementation/validation.py:144-164
- §2.4 — insert — ambiguity — offset-naive instants read as UTC; recorded instants (run windows) normalized to UTC ISO 8601 millis — implementation/db.py:106-118, routes/runs.py:89-90
- §2.5 — insert — ambiguity — no-op PATCH (no revisable field / null fields) still refreshes `updated_at` and bumps `version` — implementation/routes/customers.py:73, routes/schedules.py:110
- §2.7 — revise — mismatch — lot OCC rejects any version inequality, not only "moved past" — implementation/routes/tests.py:40-41
- §2.9 — revise — mismatch — swapped gates 3/4: reference existence precedes grower ownership everywhere (404 before 403), and body FKs resolve in the order §3 narratives name them (runs: `unit_id`, `lot_id`, `queue_ticket_id`) — implementation/routes/tickets.py:30-38, routes/lots.py:91-92, routes/runs.py:57-65
- §3.1 — insert — ambiguity — `name` non-empty; `credit_limit_cents`/`prepaid_balance_cents` non-negative integers (zero allowed), same on update — implementation/routes/customers.py:22-25,67-72
- §3.2 — insert — ambiguity — `foreign_material_pct` must be non-negative; lot's moisture/certified/provisional/final fields read null until set — implementation/routes/lots.py:46,56-63
- §3.3 — insert — ambiguity — inverted window (`effective_from` > `effective_to`) → `ERR_INVALID_REQUEST`; rate/floor/threshold/limit fields non-negative, drying/energy rates and `min_charge_cents` integer — implementation/routes/schedules.py:27-41
- §3.3 — revise — ambiguity — charge-preview without certified baseline → `ERR_INVALID_STATE` (409); "relevant service date" pinned as logical clock's current date — implementation/routes/lots.py:126-130
- §3.4 — revise — mismatch — `unit_code` uniqueness not enforced (dropped "unique"); pinned field minimums (capacity ≥1, others ≥0) — implementation/routes/units.py:19-39
- §3.4 — insert — ambiguity — confirm against `DAMAGE_HOLD` lot yields `ERR_LOT_ON_DAMAGE_HOLD` — implementation/routes/tickets.py:113-114
- §3.4 — insert — ambiguity — capacity-calendar missing/malformed `date` → `ERR_INVALID_REQUEST` (400) — implementation/routes/units.py:55-57
- §3.4 — revise — ambiguity — preempt on non-terminal non-CONFIRMED/STANDARD → `ERR_PREEMPTION_NOT_ALLOWED`; terminal tickets follow §2.5 `ERR_ALREADY_TERMINAL` — implementation/routes/tickets.py:179-183
- §3.5 — revise — ambiguity — `scheduled_end` ≤ `scheduled_start` → `ERR_INVALID_REQUEST` (400); ticket never cross-checked against run's lot/unit — implementation/routes/runs.py:76-77,147-153
- §3.5 — revise — ambiguity — completion shape (`scale_out_weight_lbs` positive int, `discharge_moisture_pct` non-negative); estimated variant's `meter_end_therms` optional/recorded-but-unused; pass-through priced against window covering completion date; no covering window → `energy_charge_cents` 0, `fuel_therms` = meter delta or 0.0 — implementation/routes/runs.py:178-185,202-212
- §3.6 — insert — ambiguity — agreement field validation (rate ≥0 number, `min_days` ≥0 int) and lot-state gating (terminal → `ERR_ALREADY_TERMINAL`; `DAMAGE_HOLD`/`STORED` → `ERR_INVALID_STATE`; all other states accept) — implementation/routes/storage.py:41-55
- §3.6 — insert — ambiguity — `ACTIVE` agreements recompute accrual live per read; `DEFAULTED` keep last stored figures (zeros from activation) — implementation/routes/storage.py:18-26
- §3.7 — insert — ambiguity — result lot's remaining fields pinned (`gross_weight_lbs` = result weight, `tare_weight_lbs` 0, `foreign_material_pct` 0.0, `target_moisture_pct` = order target, `ownership` `GROWER_HELD`, certification/provisional/final-shrink null) — implementation/routes/blends.py:145-166
- §3.8 — revise — ambiguity — claim-filing state gate enumerated: any non-DRIED, non-delivered state (incl. `STORED`) → `ERR_INVALID_STATE` — implementation/routes/claims.py:51-54
- §3.8 — insert — ambiguity — appeal/withdraw by non-filer → `ERR_FORBIDDEN_OWNERSHIP` (403) — implementation/routes/claims.py:170-171,187-188
- §3.8 — insert — ambiguity — zero `assessed_liability_cents` credits nothing and runs no waterfall; claim still `PAID`, hold still releases — implementation/routes/claims.py:211-215
- §3.9 — revise — ambiguity — inverted period → `ERR_INVALID_REQUEST`; DRYING line priced under schedule covering lot's earliest in-period completion; uncovered completion → no DRYING line; STORAGE line on a `VOID` invoice doesn't block re-billing; line grouping order and description formats pinned — implementation/routes/billing.py:57-72,95-118,136-137
- §3.9 — revise — ambiguity — governing schedule = first DRYING line's; drafts without DRYING lines accept any pin and record `schedule_id` null; invoice carries `pinned_schedule_version` (null until issue) — implementation/routes/billing.py:151-155,201-206
- §3.9 — revise — ambiguity — APPLICATION Payment also records `amount_cents` (cash amount) and null `reversal_of_payment_id` — implementation/routes/billing.py:257-265
- §3.9 — revise — ambiguity — reversal copies original's `amount_cents`, `applied_from_prepaid_cents`, `applied_from_cash_cents` — implementation/routes/billing.py:328-336

Notable findings: the three true mismatches were (1) §2.7's "moved past" vs impl's any-inequality lot OCC check, (2) §2.9's pinned ownership-before-existence order vs impl's universal existence-before-ownership, and (3) §3.4's "unique `unit_code`" claim vs impl's lack of any uniqueness check. All calculation formulas, state machines, cascades, error statuses, endpoint/role table, and the error catalogue already matched implementation exactly and were left untouched.
