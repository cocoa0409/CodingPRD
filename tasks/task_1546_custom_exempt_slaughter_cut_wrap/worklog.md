# Worklog — task_1546_custom_exempt_slaughter_cut_wrap

## Step 1: Create Task Directory — 2026-08-13T00:00:00.000Z

Task directory and workspace/ subdirectory were pre-created and pre-assigned by the orchestrating pipeline; Step 1 treated as DONE per command args.

## Step 2: Generate Scaffold — 2026-08-13T20:39:33.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1546_custom_exempt_slaughter_cut_wrap/` and pass `scaffold_lint.py` with a clean verdict (669 calls scanned across both design files, zero violations, all FKs reverse-reachable).

**Design summary** — custom-exempt locker plant, archetype compliance/audit + temporal windowing, flat topology, cyclic state-machine shape, hierarchical-override roles (Customer entity-backed; PlantOperator/PlantManager opaque):

**SCAFFOLD.yaml** (§1.0–§1.7; no design keys inline):
- **9 entities**: Customer (strike-derived status ACTIVE/ELEVATED_DEPOSIT/BLOCKED), CapacityDay (head-count kill slots), Appointment (deposit, lead time, reschedule), Animal (tag identity through RECEIVED→…→READY), CarcassShare (split ownership fractions), CutSheet (yield instructions), Invoice (hanging-weight billing), StorageRecord (freezer window), LabelRecord (NOT FOR SALE compliance gate)
- **7 state machines** incl. two non-linear ones: CutSheet DRAFT⇄SUBMITTED revision cycle, Appointment reschedule self-loops with capacity rebalance; auto-transitions (appointment completion bubble-up, run-daily expiry/no-show/abandonment sweeps)
- **7 calculations** incl. dual variants (deposit flat vs elevated 50%-of-estimate; invoice provisional estimate-weight vs final actual-weight), tiered processing fee (mode a), deposit-credit waterfall with pinned per-share-round-then-residual order (mode b)
- **24 validations** in 9 priority tiers; **41 endpoints** (incl. `/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default, and `run-daily` ops checkpoint); **24 errors** (all triggerable); **2 OCC concurrency rules** (reschedule, revise — both true races passing the serial-observability filter)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances, 2 per rule, each with literal-computed asserts (verified by executing the formulas: e.g., provisional 32120 vs final 30250; elevated deposit 38620; credit split 2498/2498/2504; tier boundary 17000 vs 17075).

**SCAFFOLD_CORNER_DESIGN.yaml**: 44 instances total — 39 active (entities/defaults, terminal lockdowns, bubble-ups, boundary violations, all 24 error triggers, RBAC denials, OCC stale-version 412s, pagination envelope, immediate consistency) + 5 `excluded_because` stubs cross-referencing §1.8 coverage. All instance names unique across both files.

One arithmetic hazard caught during verification: the tier-boundary fixture originally used 200.1 lb, which is float-fragile (`0.1×75` lands below 7.5 in IEEE754); changed to 201.0 lb → deterministic 17075.

## Step 3: Copy Shared Files — 2026-08-13T20:39:40.000Z

Copied ./INSTRUCTION.md to tasks/task_1546_custom_exempt_slaughter_cut_wrap/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T20:52:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1546_custom_exempt_slaughter_cut_wrap/workspace/PRD.md` (6,367 words). The withheld design files were not opened or referenced.

## Document structure

**§1 Introduction** — 2 paragraphs from the business-context angle (custom-exempt regulatory niche, capacity-bound seasonal operations, logical-clock testability).

**§2 Global Specifications (10 subsections)** — 2.1 RBAC (headers, three roles, per-role identity semantics incl. the Customer ownership chain via `customer_id`/`owner_customer_id`/share-linked resources); 2.2 API Response Structure (emitted **byte-identical** to the canonical source — verified by diff); 2.3 Pagination (limit 10/1/100, `offset` 0, `created_at` ascending); 2.4 Logical Clock (default `2026-08-01T00:00:00Z`, `to_iso8601`); 2.5 Common Resource Properties; 2.6 Money/Weights/Rounding (integer cents, half-up, 1-decimal pounds, whole days); 2.7 OCC (both rules: `expected_appointment_version` on reschedule, `expected_cut_sheet_version` on revise, `ERR_STALE_VERSION`/412, no other endpoint takes a version); 2.8 Existence Checking and Validation Order (left-to-right path validation plus the full 9-tier priority ordering with two worked cross-tier examples); 2.9 Cascades/Bubble-Ups; 2.10 Custom-Exempt Labeling Regime.

**§3 Business Logic (8 subsections)** — chronological lifecycle: capacity/booking (deposit_quote STANDARD vs ELEVATED with all constants), deposits/reschedule/cancel/expiry (48h window, 14-day lead, 7-day refund), drop-off→hanging (tag uniqueness, bubble-up), splits and cut sheets (fraction-sum rules, both waterfall allocations with residual-to-largest-share pinning, submit/revise cycle), fabrication/freezer/storage (3-day hang, 4-unit half-open freezer windows, 7-free-days/500-cent accrual), invoicing (tiered processing rates, PROVISIONAL vs FINAL variants, payments, waive override), label approval/pickup gates, and the no-show/abandonment/strike policy with the daily sweep.

**§4** — 41-row endpoint table (4 columns only). **§5** — 24-row error catalogue (2 columns only).

## Hard-contract reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 63 required, 63 present, 0 missing
Status: PASS

Rule coverage check:
- validation priority ordering: expressed in §2.8 prose with cross-tier examples
- concurrency_rules: 2/2 expressed (endpoint + occ field + ERR_STALE_VERSION/412)
- state-machine transitions: 33/33 expressed (preconditions paired with error IDs, all side effects incl. cascades)
- calculations: 7/7 expressed in reconstructible prose (no pseudocode, no fuzzy words — mechanically verified)
- validations: 21/21 matchable to error IDs in §2/§3; all 24 error IDs appear in prose
- endpoint side effects / applies_to: all covered
Status: PASS

Path purity check (§3 only):
- 342 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos
Status: PASS
```

Entity coverage: all 9 entities (Customer, CapacityDay, Appointment, Animal, CarcassShare, CutSheet, Invoice, StorageRecord, LabelRecord) with every scaffold field named in backticks, all enum/state values verbatim, and all numeric constants embedded in business context.

## Step 5: Generate Unit Tests — 2026-08-13T21:50:44.000Z

Done. Summary of what was generated for `task_1546_custom_exempt_slaughter_cut_wrap`:

## Helper files created (`test_helpers/`, 9 files)
- `types.py` — 10 status enums (Customer/CapacityDay/Appointment/Animal/CarcassShare/CutSheet/Invoice/StorageRecord/LabelRecord + Species/IntendedUse/UserRole) and 9 TypedDicts, all with the full common-field set (id, created_at, updated_at, version per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 38 methods, one per PRD §4 endpoint including `/_clock/set_current_utc`
- `api_errors.py` — `ApiErrorId` (24 errors) + HTTP status map, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_invoice_invariants` (amount_due = max(0, total − paid))
- `factories.py` — payload factories for all write endpoints (input fields only)
- `constants.py` — domain thresholds/rates from PRD §3 (deposits, dress %, tiered rates, storage, abandonment, strikes)
- `test_users.py` — opaque operator/manager shared headers + `make_customer_headers(user_id)` builder for the entity-backed Customer role
- `fixtures.py` — 5-tier composite helpers: CRUD wrappers, `book_appointment`/`pay_full_deposit`/`book_and_confirm`, animal lifecycle (`process_animal_to_hanging`, `start_and_complete_fabrication`), scenario builders (`setup_hanging_animal`, `setup_finalized_single_share`, `setup_ready_share`, `earn_no_show_strike`, `setup_customer_with_collections`). All flows keep the logical clock monotonic (no backward `set_current_utc`), since PRD §2.4 only guarantees advancing the clock.
- `__init__.py` — barrel export

## Tests emitted (`test_suite/`, 6 files, 75 tests; pytest collection verified)
- Queue A (Difficulty): **18/18 instances, 2 tests each = 36 tests** — e.g. `invoice_provisional_vs_final_settlement` (32120 vs 30250), `deposit_flat_vs_elevated_quote` (15000 vs 38620), `deposit_credit_per_share_rounding_then_residual` (2498/2498/2504), tiered+storage total 40000/PAID, both priority-pair orderings, both boundary pairs (14-day lead, day-7/8 storage), both cascades, both OCC… all with literal values copied from the design YAML.
- Queue B (Corner): **39/39 non-stub instances, 1 test each = 39 tests**. The 5 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve.
- Every test docstring carries verbatim PRD citations (machine-checked: every quoted fragment greps literally against PRD.md) and ends with exactly one `Design:` tag resolving to a real instance (machine-checked against both YAMLs). No skip/xfail markers anywhere; no scaffold references in comments.

## Instances skipped with reasons
None — zero instances skipped. Two assertion-level deviations where the design YAML asserted PRD-underdetermined values (these are *not* instance skips; the tests were emitted with the assertion weakened to the PRD-derivable form, per the Core rule):
1. `customer_creation_applies_defaults` — dropped literal `version == 1` (PRD §2.5 says version "starts at creation" without pinning 1) and created_at string equality (PRD requires three fractional digits, so exact `"2026-08-01T00:00:00Z"` format is not derivable); instead asserts ACTIVE/0 strikes/bare UUID and that `created_at` parses to the logical-clock default instant.
2. Version assertions in the CutSheet/reschedule cycle tests use relative +1 increments from captured versions (PRD §2.5 "increments by exactly 1 on every mutation") rather than the YAML's absolute 2/3/4, which assume version starts at 1.

One setup-mechanics note: several design recipes reset the clock backwards (e.g. to 2026-08-01 after a no-show). Because PRD §2.4 describes `set_current_utc` as *advancing* the clock, the affected flows (`deposit_flat_vs_elevated_quote`, `second_strike_blocks_booking`, `abandonment_cascade_*`, `booking_lead_time_beats_outstanding_balance`, `collections_invoice_blocks_booking`) were restructured to monotonic timelines with later capacity days (08-29/08-30/08-31/09-04/09-10/09-13), preserving every asserted literal (11875, 38620, 5000 surcharge, etc.).

## Step 6: Generate Implementation — 2026-08-13T21:50:44.100Z

Done. The implementation is complete and the full benchmark suite passes twice (75/75, then 75/75) under `prd-bench-local-run --isolation per-test-server`.

## Summary

**Files created** in `/home/ubuntu/github/CodingPRD/tasks/task_1546_custom_exempt_slaughter_cut_wrap/workspace/implementation/`:
- `start.sh` — guarded launcher (skips `pip install` when flask is importable; `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` — flask
- `app.py` — all routes, validation pipeline (auth → RBAC/ownership → existence → well-formedness → state/OCC → resale-safety → business → temporal → referential → fiscal), cascades, sweeps
- `db.py` — in-memory stores + logical clock (default `2026-08-01T00:00:00Z`); empty at boot, no seeding
- `errors.py` — all 24 catalog error IDs with exact HTTP statuses
- `response.py` — envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list `meta` carries `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-Role`/`X-User-ID` auth for roles Customer/PlantOperator/PlantManager
- `calc.py` — constants and all calculation rules (Decimal, ROUND_HALF_UP)
- `serializers.py` — entity payloads with live computed views

**Endpoints: 38** (all scaffold routes; the clock is registered at `/_clock/set_current_utc` per PRD, plus the prefixed alias for safety).

**State machines: 8** — Appointment (PENDING_DEPOSIT→CONFIRMED/CANCELLED/EXPIRED, CONFIRMED→CANCELLED/NO_SHOW/COMPLETED, reschedule self-loops), Animal (EXPECTED→RECEIVED→SLAUGHTERED→HANGING→CUTTING→READY→COMPLETE + VOIDED cascade), CarcassShare (PENDING→CONFIRMED→READY→PICKED_UP/FORFEITED), CutSheet (DRAFT⇄SUBMITTED revise cycle, →LOCKED), Invoice (OPEN→PARTIALLY_PAID→PAID, OPEN/PARTIALLY_PAID→COLLECTIONS, COLLECTIONS→PAID), StorageRecord (STORED→PICKED_UP/ABANDONED), LabelRecord (PENDING→APPROVED with RESALE forbidden), plus Customer standing derivation. Version bumps on every mutation including cascades; OCC via `expected_appointment_version`/`expected_cut_sheet_version` → 412.

**Calculations: 7** — deposit_quote (STANDARD flat vs ELEVATED 50%-of-value; verified BEEF 15000 vs 38620), invoice_settlement (200-lb marginal tiers; PROVISIONAL vs FINAL verified at 32120 vs 30250), deposit_credit_allocation (per-share round-half-up then residual to largest fraction; verified 2498/2498/2504), share_weight_allocation (same residual discipline, sums exactly), storage_fee (calendar-date day counts, 7 free days, 500/day, abandon at days>21), cancel_refund_policy (7-day boundary), customer_strike_policy (1→ELEVATED_DEPOSIT, 2→BLOCKED).

**Notable semantics implemented**: computed `booked_head` from live appointment statuses; logical-clock timestamps emit `...T00:00:00Z` when whole-second; payment on a PAID invoice is rejected with 409 only when its recomputed balance is zero (accrual since last payment reopens a settleable balance, per the §3.7 pickup gate); pickup finalizes storage at the pickup instant; run-daily sweeps expiry (strictly past due), auto no-show (strictly past date), and abandonment with the depth-3 cascade (share FORFEITED → invoice COLLECTIONS+5000 surcharge → customer strike), returning the three ID lists.

**Test-side fix (outside implementation)**: `test_suite/test_05_invoices_storage_labels_pickup.py` had a generator bug — `_setup_freezer_full_scenario(self)` referenced the `api` fixture without receiving it (NameError in 2 tests). Patched to `_setup_freezer_full_scenario(self, api)` at the definition and both call sites; both freezer tests now run and pass against the implementation.

## Step 7: Run Tests and Iterate — 2026-08-13T21:55:00.000Z

All 8 parallel rounds passed 75/75 on the first iteration — the suite is stable.

**Summary**
- Iterations run: 1 (single 8-round parallel sweep; all rounds completed with `passed == total` = 75/75).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none this iteration (prior history noted one Step-6-era fix to `test_suite/test_05_invoices_storage_labels_pickup.py` for `_setup_freezer_full_scenario(self, api)`; verified stable).
- Fixes applied to `implementation/`: none.

No flakiness surfaced across the 8 concurrent rounds — no failing tests to union, no diagnostic steps needed. Exiting per the clean-sweep condition.

## Step 8: Finalize PRD — SKIPPED — 2026-08-13T21:55:10.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes in Step 7 itself. Per the skip condition, Step 8 is skipped; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-08-13T22:13:50.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1546_custom_exempt_slaughter_cut_wrap/workspace/PRD_COMPLETED.md` (copied from PRD.md, then edited in place; PRD.md untouched).

**Size**: PRD.md 258 lines / 43,996 chars → PRD_COMPLETED.md 260 lines / 46,657 chars (delta +2 lines, +2,661 chars).

**Counts**: 16 ambiguity-pins, 5 mismatch-revisions (21 changes total).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — insert — ambiguity — pins Customer animal-ownership (booking customer of the appointment or owner of any share) and Customer-self-read rule for `GET /locker/customers/{id}` (else ERR_FORBIDDEN) — app.py:225-235, 375-376.
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is wall-clock, not logical — response.py:14-17.
- §2.3 — insert — ambiguity — pins ERR_INVALID_REQUEST for limit<1/>100, negative offset, non-integer pagination; created_at ties break in creation order; `has_more` = offset + returned < total_count — app.py:153-178, response.py:45-46.
- §2.4 — insert — ambiguity — clock set accepts any instant (no monotonicity) and is also mounted at `/locker/_clock/set_current_utc` — app.py:330-341.
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — app.py:188-194.
- §2.5 — insert — mismatch — logical-clock timestamps omit the fractional part on whole-second instants (vs "three fractional digits" absolute) — calc.py:93-102.
- §2.6 — revise — mismatch — hang time removed from calendar-date day-count list; it is an elapsed-duration gate — app.py:723, calc.py:39.
- §2.8 — insert — ambiguity — non-object JSON body → ERR_INVALID_REQUEST; absent/unparsable body treated as empty object — app.py:93-99.
- §2.10 — revise — ambiguity — pins exact label_text template `NOT FOR SALE — {owner name} — {SPECIES} carcass share {share_fraction} (animal tag {tag_id})` — app.py:866-868.
- §3.1 — insert — ambiguity — `booked_head`/`status` derived at read time; CapacityDay row/version never mutated by booking activity — serializers.py:65-70, 109-120.
- §3.1 — insert — ambiguity — `date_from`/`date_to` filters are inclusive — app.py:415-418.
- §3.1 — insert — ambiguity — no uniqueness enforced on customer name/phone/email — app.py:348-361.
- §3.2 — revise — ambiguity — reschedule evaluates capacity ahead of lead time (§2.8 tier order), correcting the sentence's misleading enumeration order — app.py:603-604.
- §3.4 — insert — ambiguity — repeated finalization (all shares already CONFIRMED) fails with ERR_INVALID_STATE — app.py:828-830.
- §3.4 — insert — ambiguity — finalize responds 200 with `response_type: "array"` of all the animal's shares in creation order — app.py:872, response.py:32-42.
- §3.4 — revise — ambiguity — yield threshold is the flat value 60 (grind_pct > 60 rejected; exactly 60 accepted), not a fraction of trimmable weight — app.py:996-997, calc.py:40.
- §3.5 — revise — mismatch — minimum hang is 72 hours elapsed from the `weighed_at` instant, not three calendar-date boundaries — app.py:723.
- §3.5 — insert — ambiguity — ABANDONED records freeze days_stored/accrued_fee_cents at the sweep-stamped values; list responses reflect the same as-of-now view — serializers.py:77-88, app.py:1236-1239.
- §3.6 — revise — mismatch — a PAID invoice is terminal only while its recomputed amount due is zero; reopened storage accrual on PAID accepts further payment (PRD had said PAID always rejects) — app.py:1062-1076.
- §3.6 — revise — mismatch — a partial payment on a COLLECTIONS invoice leaves it in COLLECTIONS (PRD had said any underpayment moves to PARTIALLY_PAID) — app.py:1075-1077.
- §4 — insert — ambiguity — undeclared paths and unsupported methods on declared paths return ERR_NOT_FOUND (404) — app.py:72-79.

Key findings worth flagging: the two genuine behavioral mismatches are in §3.6 payments (PAID invoices with reopened storage balances accept payment; partial payments never move COLLECTIONS→PARTIALLY_PAID) and the §3.5 minimum-hang gate, which the implementation evaluates as an exact 72-hour elapsed-duration check while the PRD's §2.6/§3.5 prose implied calendar-date-boundary counting. All calculation formulas, state machines, role tables, error tiers, and cascade rules otherwise matched the PRD as written.

## Pipeline Complete — 2026-08-13T22:13:50.000Z

All steps 1–9 completed. Final state: 75/75 tests passing across an 8-round parallel stability sweep under per-test-server isolation; PRD_COMPLETED.md produced.
