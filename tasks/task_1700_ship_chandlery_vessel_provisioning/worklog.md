# Worklog — task_1700_ship_chandlery_vessel_provisioning

## Step 1: Create Task Directory — 2026-08-14T09:08:04.258Z

Task directory `tasks/task_1700_ship_chandlery_vessel_provisioning/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per entrance instructions. No index scan performed, no other task_* directory touched.

Difficulty directive from requester: "Generate task hard than expert level!" — passed to scaffold generation as a max-depth/max-breadth directive.

## Step 2: Generate Scaffold — 2026-08-14T10:08:37.248Z

Done. Scaffold for task_1700_ship_chandlery_vessel_provisioning generated from scratch (no sibling tasks consulted), lint-clean on the first full run.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD.yaml
  Difficulty design:  tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  776

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD.yaml` | 1,555 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,966 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/SCAFFOLD_CORNER_DESIGN.yaml` | 2,127 |

## Counts

- **Entities: 12** (ShipAgent, VesselCall, CatalogItem, StockLot, Requisition, Quotation, Order, Delivery, Invoice, Payment, QualityComplaint, CreditNote)
- **State machines: 8** — incl. parallel dims (Order fulfillment × payment; VesselCall status × customs_clearance_status) and cycles (Quotation SENT→SENT revise, Requisition recall, QualityComplaint reopen)
- **Calculations: 10** — incl. dual-variant line_pricing (provisional/final) and agent_credit_exposure (committed/settled), tiered cold-chain surcharge, pinned rounding order, pinned rebate evaluation order, FIFO reservation waterfall, FX tolerance settlement, credit-note math
- **Validations: 28** ordered rows across auth/existence/state/OCC/safety/temporal/constraint/referential/fiscal
- **Endpoints: 50** (incl. test-driving `POST /chandlery/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default)
- **Errors: 53** (all referenced by ≥1 validation/transition; one unreachable guard error was found during self-audit and removed)
- **Roles: 8** — segregation_of_duties model (warehouse creates vs vessel confirms; QA reviews vs finance owns credit; four-eyes re-review after complaint reopen), 2 entity-backed roles (VesselCateringOfficer→VesselCall, ShipAgentClerk→ShipAgent)
- **§1.8 difficulty instances: 24** across all 9 rules (3 each for rules 2, 3, 5, 6, 7, 9; 2 each for rules 1, 4, 8), every differentiation clause satisfied with distinct domains/modes/pairs/metrics; all numeric asserts are precomputed literals (e.g. provisional 576,000 vs final 480,000; per-line duty 34 vs sum-round 33; 72h tier boundary 28,600 vs 28,720)
- **§1.9 corner instances: 43** (40 active + 3 `excluded_because` stubs) across all 9 claim-extraction sections

## Notes

- Endpoint/error counts exceed the §0.4 Expert *guideline* ceilings (32/30); §0.4 marks those "guidelines, not hard rules", and the excess is forced by the mandatory FK reverse-reachability GETs and per-transition endpoints — documented in the SCAFFOLD.yaml header comment.
- Two design holes were caught and fixed during self-audit: an unreachable error (`ERR_DELIVERY_BLOCKED_BY_INVOICE` — removed from catalog and preconditions, replaced by a pinned delivery-create quantity cap), and one occurrence of forbidden vocabulary ("simultaneously" in a field description — reworded).
- Both concurrency rules are true OCC races (quotation revise, stock adjustment) with `expected_*_version` payloads referencing captured `${var}`s per lint rule (e).

## Step 3: Copy Shared Files — 2026-08-14T10:09:08.528Z

Copied `./INSTRUCTION.md` → `tasks/task_1700_ship_chandlery_vessel_provisioning/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-14T10:15:38.321Z

All audits pass. Final summary:

## PRD Generation Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/workspace/PRD.md`
**Line count:** 319 lines

**Section list:**
- §1. Introduction (2 paragraphs: business context + design commitments)
- §2. Global Specifications & System-Wide Principles
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure (verbatim contract block)
  - §2.3 Pagination
  - §2.4 Common Resource Properties and the Logical Clock
  - §2.5 Money, Precision, and Rounding
  - §2.6 Optimistic Concurrency Control
  - §2.7 Credit Exposure Accounting
  - §2.8 Dual-Variant Pricing: Provisional versus Final
  - §2.9 Parallel Status Dimensions and Cascade Discipline
- §3. Business Logic & Workflows (14 subsections, lifecycle-driven: agents/catalog → warehouse → requisition → quotation → reservation waterfall → delivery → cancellation/departure → customs → invoicing → payments → rebate → complaints → credit → substitution)
- §4. Endpoint Definitions (49 endpoints, 4-column table)
- §5. Error Code Catalogue (53 error IDs, 2-column table)

**Coverage self-audit (Zero-Silence Rule):**

- **Contract 1 — Field-Name Coverage:** 91 required identifiers (entity fields + endpoint `input`/`query_params`/`path_params` + pagination tokens), all present in backticks. After initial pass found `delivery_id`, `order_id`, `requisition_id` missing, three surgical prose additions closed the gap. Final diff: **0 missing. PASS.**
- **Contract 2 — Rule Coverage:**
  - Validations: all 24 priority-ordered entries surfaced in prose with paired `error_id`, including priority-1 auth header check (§2.1), priority-2 ownership check (§2.1), priority-6 OCC (§2.6 + §3.2/§3.4), priority-7 customs gate (§3.6), priority-9 segregation of duties (§3.6 + §3.12), priority-12 lazy expiry (§3.4), priority-16 substitution price cap with inclusive boundary (§3.14), priority-23 credit limit with inclusive-accept boundary (§3.4), priority-24 overpayment tolerance (§3.10).
  - Concurrency rules: both OCC entries (quotation-revise, stock-adjustment) expressed with `expected_quotation_version` / `expected_stock_lot_version` + `ERR_STALE_VERSION` 412, framed purely as stale-version rejection (§2.6).
  - State machine transitions: all 8 entities' machines covered — VesselCall (arrive/depart/cancel/customs × 4 transitions), Requisition (submit/recall + 4 system transitions), Quotation (send/revise-cycle/accept/lazy-expire/withdraw × 2), Order (parallel-dimension transitions incl. CREDITED↔INVOICED/PARTIALLY_PAID compensation), Delivery (dispatch/confirm/cancel × 2/fail × 2), Invoice (all 8 transitions), QualityComplaint (accept/reject/reopen with four-eyes), CreditNote (revoke).
  - Calculations: all 9 rules (`line_pricing` dual-variant, `order_totals` pinned rounding order, `volume_rebate` pinned evaluation order + no-re-eval rule, `duty_split`, `stock_reservation_waterfall` FIFO + half-open overlap, `agent_credit_exposure` dual-variant + currency caveat, `credit_limit_check` inclusive boundary, `fx_payment_settlement` ±50 tolerance bands, `credit_note_amount` selector + restocking floor + min-cap) expressed in precise business prose, no pseudocode, no fuzzy hedging.
  - Endpoint side effects: every `side_effects` entry (cascades on depart, order-cancel, complaint-accept, credit-revoke, invoice issuance, payment) expressed in §3 narrative.
  - Sibling-branch symmetry: PENDING/CLEARED/REJECTED customs transitions, DRAFT/SENT withdrawal branches, ISSUED/PARTIALLY_PAID credit-flip branches all rendered at equal density.
  - **PASS.**
- **Contract 3 — §3 Path Purity:** 453 backticked tokens in §3 scanned; 0 start with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS.**

All state enumeration values, role names, error IDs, and entity field names from the scaffold appear verbatim in backticks somewhere in the PRD.

## Step 5: Generate Unit Tests — 2026-08-14T11:01:35.696Z

Done. Here is the summary.

## Files written

**`test_helpers/`** (under `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/test_helpers/`):

| File | Contents |
|---|---|
| `types.py` | 9 status enums + role enum + 12 entity TypedDicts. `Payment` (common_fields: false) correctly omits `updated_at`/`version`. |
| `constants.py` | Rebate tiers (500k/4%, 1M/7%), cold-chain tiers (72h kink, 5/12 cents), 50-cent payment tolerance, restocking fee (min 500, 5%), 115% substitution cap, shared ETA/ETD schedule. |
| `api_errors.py` | All 53 PRD §5 error IDs + HTTP status map, registered with the framework via `set_error_http_status_map`. |
| `api_client.py` | `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (36 business + clock methods). |
| `test_users.py` | `TEST_USERS` shared constants for the 6 opaque roles + per-instance builders `make_officer_headers` / `make_clerk_headers` / `make_qa_headers` for the entity-backed roles. |
| `factories.py` | Payload factories (input fields only) with a uniqueness counter for sku/lot_code/imo. |
| `assertions.py` | Per-entity `assert_<entity>()` + `assert_invoice_money_conservation` + `assert_stock_conservation`. |
| `fixtures.py` | Tiered composites: leaf creators → `create_submitted_requisition` → `create_sent_quotation` → `setup_accepted_order` → `setup_delivered_order` → `setup_invoiced_order` → `setup_accepted_credit_note`, with entity-backed identity threading. |
| `__init__.py` | Barrel export of framework generics + all PRD-specific names. |

**`test_suite/`** (12 test files + conftest, 91 tests total):

| File | Tests | Queue |
|---|---|---|
| `conftest.py` | — | — |
| `test_01_pricing_variants.py` | 10 | A (dual_variant_calc ×2 instances, combinatorial_formula ×3) |
| `test_02_state_machines.py` | 6 | A (non_linear_state_machine ×3) |
| `test_03_credit_cascades.py` | 4 | A (transitive_cascade ×2) |
| `test_04_validation_priority_pairs.py` | 6 | A (priority_pair_validation_conflict ×3) |
| `test_05_boundaries.py` | 6 | A (boundary_precision_check ×3) |
| `test_06_cross_entity_and_overlap.py` | 10 | A (cross_entity_state_dependency ×3, resource_temporal_overlap ×2) |
| `test_07_compensating_invariants.py` | 6 | A (compensating_invariant ×3) |
| `test_08_entity_corners.py` | 7 | B (entities ×7) |
| `test_09_state_machine_corners.py` | 6 | B (state_machines ×6) |
| `test_10_calculation_corners.py` | 6 | B (calculations ×5, one with 2 tests) |
| `test_11_validation_corners.py` | 10 | B (validations ×9, one with 2 tests) |
| `test_12_endpoints_rbac_concurrency.py` | 14 | B (endpoints ×3, errors ×2, rbac ×4, cross_cutting ×3, consistency ×1) |

## Totals

- **Total tests emitted: 91** (pytest collects 91 cleanly).
- **Queue A (Difficulty): 48 tests** — all 24 instances × exactly 2 tests.
- **Queue B (Corner): 43 tests** — all 40 non-stub instances covered (5 instances got 2 tests each for boundary polarity).

## Instances skipped (PRD-first filter)

None. Every non-stub instance passed both conditions (verbatim PRD coverage + unique derivability). The 3 `excluded_because:` stubs — `Corner/calculations/dual_variant_calc_coverage_stub`, `Corner/cross_cutting_layers/cascading_side_effects_stub`, `Corner/errors/error_catalog_coverage_stub_for_state_errors` — were correctly NOT translated (their difficulty-design instances own the assertions; all cross-references resolve).

## Stage 2 self-audit verdict

**PASS.**
- All 91 emitted tests carry exactly one `Design:` tag; every tag resolves verbatim to a real `name:` in the source YAML (scripted audit).
- Coverage: every queue-A instance has ≥2 tests; every non-stub queue-B instance has ≥1 test; no shortfalls.
- PRD-citation verbatim pass: all 99 quoted PRD passages across the 91 docstrings survive a literal whitespace-tolerant grep of `PRD.md` (0 failures after fixing one elided quote).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- All files compile; all 91 tests collect under `pytest --collect-only`.

## Step 6: Generate Implementation — 2026-08-14T11:01:35.696Z

Done. Here is the summary.

## Implementation complete: task_1700_ship_chandlery_vessel_provisioning

**Test result: 86/91 passed** under `prd-bench-local-run --isolation per-test-server` (fresh server boot via `start.sh` before every test). The 5 remaining failures are all test-side defects, none fixable from the implementation:

1. `test_revoke_flips_note_to_revoked` and `test_revoke_restores_invoice_and_agent_exposure` — `NameError: name '_dict' is not defined` in `test_suite/test_03_credit_cascades.py` (lines 104, 132 call an undefined helper `_dict(...)`).
2. `test_substitution_price_cap_boundary` — fixture bug in `test_helpers/factories.py::create_requisition_payload`: `allows_substitution=True` is applied as a top-level payload override, so the requisition line keeps `allows_substitution: false`; the API's `ERR_SUBSTITUTION_NOT_ALLOWED` is the correct response per PRD §3.14.
3. `test_final_duty_free_after_clearance_diverges` and `test_settled_catches_up_after_invoicing` — their setups schedule a bonded-item delivery while customs is PENDING, which the PRD §3.6 gate ("bonded_eligible items require CLEARED at scheduling time") forbids. The design doc for the duty-flip scenario specifies CLEARED *before* delivery; the generated test dropped that step. Three other tests (`test_bonded_delivery_pending_clearance_rejected`, `test_customs_gate_masks_window_containment`, `test_bonded_delivery_after_clearance_succeeds`) pin the gate literally, so I kept the PRD-faithful behavior. Note `test_credit_note_revoke_from_revoked_rejected` uses `clear_customs=True` for exactly this reason, confirming the oversight.

### Files written (all under `.../workspace/implementation/`)
| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 52 |
| `db.py` | 117 |
| `errors.py` | 258 |
| `response.py` | 80 |
| `middleware.py` | 73 |
| `routes/core.py` (clock, agents, vessel calls) | 265 |
| `routes/catalog.py` (catalog items, stock lots, adjustments) | 152 |
| `routes/requisition.py` | 128 |
| `routes/quotation.py` (draft/send/revise/accept/withdraw) | 397 |
| `routes/order_delivery.py` (orders, deliveries, confirm) | 284 |
| `routes/invoice.py` (invoices, payments) | 264 |
| `routes/complaint.py` (complaints, credit notes) | 275 |
| `services/pricing.py` (dual-variant line pricing, totals, rebate, duty split, cold tiers) | 180 |
| `services/stock.py` (reservation waterfall, cold-chain capacity, release/confirm accounting) | 147 |
| `services/exposure.py` (committed/settled agent exposure) | 45 |
| `services/money.py` (round-half-up cents, FX) | 18 |
| `services/validate.py` (body validation per priority order) | 106 |
| **Total** | **2,852** |

### Endpoints
**50/50 implemented.** (The task brief said "49-endpoint table"; the actual PRD §4 table and scaffold §1.5 both contain 50 rows — I counted both.) Every route from the endpoint table is wired, including the logical-clock test-driving endpoint.

### Error catalog
**53/53 error IDs** covered in `errors.py` with the exact HTTP statuses from the scaffold/PRD catalog (verified programmatically: zero PRD error IDs missing).

### Boot contract — confirmed
`bash start.sh` (a) guards the dependency install with `if ! python3 -c "import flask"` so per-test reboots skip pip, (b) `exec python3 app.py` in the foreground, (c) binds `0.0.0.0:$PORT` (verified listening on `0.0.0.0:18234` with a custom `$PORT`), (d) serves HTTP within ~1s of invocation (well under the 60s limit).

### Storage
Purely in-memory dicts keyed by id (`db.py`), empty at every boot. No SQLite, no JSON dump, no /tmp cache, no seeding — audited: the only match for "seed" is the docstring stating the store starts empty; no `open(`, `sqlite`, `pickle`, or file writes anywhere.

### Key spec-fidelity decisions traced to PRD/scaffold text
- **Dual-variant pricing** (provisional at quote time with current customs + planned-stay cold hours; final at issuance with delivered qty, clearance-at-issuance, actual-hours cold): order totals frozen from the quotation's provisional snapshot (`total_cents := provisional_total_cents`).
- **Payment tolerance** (§3.10): implemented as `converted vs outstanding` within ±50 cents — the only reading that preserves the pinned invariant `paid + credited + writeoff + outstanding == total` across multi-payment closes (the literal `new_paid - outstanding` formula breaks that invariant after any partial payment; the invoice field's own invariant clause and the "lands within ±50 cents of outstanding" wording disambiguate).
- **Validation priority ordering**: customs gate (7) fires before window-inverted (10), containment (11), and quantity rules (13/14) on delivery create — pinned by `test_customs_gate_masks_window_containment`.
- **Logical-clock timestamps** render at second precision (`2026-08-24T12:00:00Z`): two tests string-compare `due_date` in exactly that form, and the shared `is_iso8601_timestamp` check treats fractional digits as optional. The envelope's `meta.api_request_timestamp` keeps the PRD §2.2 three-fractional-digit form.
- **Stock model**: reserve moves `on_hand → reserved`; confirm deducts both; release adds back — matching test_07's conservation assertions (`on_hand + reserved == received`, restore-to-exact on cancel) and the cold-chain half-open overlap gate (`end == start` does not overlap).

## Step 7: Run Tests and Iterate — 2026-08-14T11:32:10.533Z

All 8 rounds clean: 91/91 passed in every round, confirmed via the JSON results files. Exiting per protocol.

## Summary

**Iterations run:** 4 sweeps + 1 single-round repro. Sweep 1 (baseline): 86/91 in all 8 rounds, same 5 deterministic failures. Sweep 2 (post-fix): the 5 original failures resolved; one transient infrastructure flake surfaced (`test_full_quantity_yields_delivered`, `ConnectionError` mid-setup in 7/8 rounds) — adjudicated below. Single-round solo run: 91/91. Sweep 3: pytest reported 8× 91-passed but results JSONs were lost to a harness/filesystem artifact on the shared host. Sweep 4 (results redirected to a private dir): **8/8 rounds clean, 91/91 each** — the exit criterion.

**Tests deleted:** none. All 5 failing tests trace to verbatim PRD prose and pass unique derivability (§3.13 revoke cascade; §2.8 dual-variant pricing; §2.7/§3.9 exposure legs; §3.14 substitution price cap with inclusive boundary).

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/test_helpers/factories.py` — `create_requisition_payload`: `allows_substitution` was being dumped at payload top level via `**overrides`, leaving the hardcoded line-level `False`; PRD §3.3 declares it a per-line field ("each line naming a `catalog_item_id`, a `requested_qty` of at least 1, an `allows_substitution` flag"). Now an explicit parameter placed inside the line dict. Fixed `test_substitution_price_cap_boundary` (implementation correctly returned ERR_SUBSTITUTION_NOT_ALLOWED against the malformed fixture).

**Fixes applied to `test_suite/`:**
- `test_03_credit_cascades.py` — `test_revoke_flips_note_to_revoked` and `test_revoke_restores_invoice_and_agent_exposure`: `**_dict(...)` → `**dict(...)` (NameError typo; intended kwargs-merge semantics unchanged).
- `test_01_pricing_variants.py` — `test_final_duty_free_after_clearance_diverges`: moved `customs_decision(CLEARED)` to before `create_scheduled_delivery`; the old order scheduled a bonded delivery while customs PENDING, tripping the PRD §3.6 customs gate. Divergence semantics preserved (quotation priced while PENDING, invoice issued while CLEARED).
- `test_01_pricing_variants.py` — `test_settled_catches_up_after_invoicing`: the `setup_invoiced_order` chain inherently schedules a bonded delivery while PENDING. Replaced with an explicit flow: accept while PENDING → CLEARED (gate satisfied) → schedule/dispatch/confirm → REJECTED (CLEARED→REJECTED permitted by §3.8) → invoice. Issuance sees REJECTED → dutiable final pricing → the asserted 576,000 totals are unchanged; docstring updated to match.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in all 5 cases — it correctly enforced the §3.6 customs gate, §3.14 line-level substitution admissibility, and the §3.13 revoke cascade.

**Flakiness adjudication:** `test_full_quantity_yields_delivered` (sweep 2 only) failed with transport-level `ConnectionError` during fixture setup — no assertion, no HTTP error, no server-side traceback in any sweep-2-era server log. The host was concurrently running foreign task sweeps (observed `/v1/...` logs of other tasks in the same window). The same test passed 8/8 in sweep 1, in the solo run, and 8/8 in sweep 4. No code change warranted.

Orchestrator note: the final sweep's results were written to `/tmp/task1700_results/results.{1..8}.json` (private dir to avoid a shared-host filesystem artifact); I copied all 8 into `workspace/implementation/results.{1..8}.json` and verified each shows passed=91 total=91 failed=0.

## Step 8: Finalize PRD — 2026-08-14T11:39:57.566Z

## Summary

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/workspace/PRD_FINALIZED.md` — created; byte-identical to `PRD.md` (verified with `diff`).

**Line counts / %-delta:** PRD.md = 319 lines; PRD_FINALIZED.md = 319 lines; delta 0 lines, 0.0%.

**Changes:** none. All five `<step_7_diff>` items are pure test/fixture bugs — the implementation was verified in source to be PRD-faithful at every site, and the PRD prose already uniquely determines each behavior (matching the diff's own adjudication: "All 5 failing tests trace to verbatim PRD prose and pass unique derivability"; "Fixes applied to `implementation/`: none"). The hard scope forbids edits not traceable to a step_7_diff PRD-silence or mismatch, so the minimal patch is the identity copy.

### Per-candidate-edit pre-edit search log (each candidate enumerated, then rejected as already-pinned)

1. **§3.3 line-level `allows_substitution`** (factories.py fix)
   - (a) Subject: where `allows_substitution` lives in the create-requisition payload and its type/requirement.
   - (b) Paths enumerated: `implementation/routes/requisition.py:20-68` (`_validate_requisition_lines` reads the flag only inside each line dict, requires JSON bool else `ERR_INVALID_REQUEST`; `create_requisition` reads only `title`/`lines` from the body); all consumers of the flag — `implementation/routes/quotation.py:123-128` (substitution admissibility); PRD §3.3 line 122 and §3.14 line 202.
   - (c) No edit: PRD §3.3 already pins per-line placement ("each line naming a `catalog_item_id`, a `requested_qty` of at least 1, an `allows_substitution` flag, and an optional `notes`"), required-by-default (only `notes` marked optional), boolean ("flag"). Pure fixture bug (top-level key was ignored; line kept `False`).

2. **§3.13 revoke cascade** (test_03 `_dict`→`dict` NameError typo)
   - (a) Subject: credit-note revoke compensation semantics.
   - (b) Paths enumerated: `implementation/routes/complaint.py:252-275` (revoke), `implementation/routes/invoice.py:35-70` (`_recompute_outstanding`, `_rederive_invoice_status`, `_sync_order_payment_status`), `implementation/services/exposure.py:27-45`; both callers of `_rederive_invoice_status` (complaint accept and credit-note revoke) checked for wording consistency.
   - (c) No edit: implementation matches PRD §3.13 lines 196-198 verbatim (REVOKED flip, subtract from `credited_amount_cents`, outstanding recompute, formerly-CREDITED returns to ISSUED or PARTIALLY_PAID, order payment dimension follows, exposures recomputed; revocation always permitted from APPLIED). Test change was a Python NameError typo with zero behavioral content.

3. **§3.6 customs gate at delivery scheduling** (test_01 `test_final_duty_free_after_clearance_diverges` ordering fix)
   - (a) Subject: bonded_eligible lines require clearance CLEARED at scheduling time.
   - (b) Paths enumerated: `implementation/routes/order_delivery.py:98-181` (gate at lines 130-133, before window and qty checks); the other two customs reach-points per §3.8 — `implementation/services/pricing.py:78-83,113-135,138-180` (provisional/final duty-free eligibility); PRD §3.6 line 148, §2.8 line 96, §3.9 line 170.
   - (c) No edit: PRD §3.6 pins the gate verbatim ("if any planned line's catalog item is `bonded_eligible`, the vessel call's `customs_clearance_status` must be `CLEARED` at scheduling time"). Test was misordered (scheduled while PENDING).

4. **§2.7/§2.8/§3.8/§3.9 exposure legs + CLEARED→REJECTED** (test_01 `test_settled_catches_up_after_invoicing` flow rewrite)
   - (a) Subjects: customs machine transitions; accept-time gates (no customs check); final pricing reading clearance at issuance; committed vs settled exposure legs at invoicing.
   - (b) Paths enumerated: `implementation/routes/core.py:225-241` (customs-clearance endpoint), `implementation/routes/quotation.py:303-370` (accept check order — SENT → expiry → IN_PORT → credit → stock → cold, no customs gate), `implementation/services/pricing.py:138-180` + `implementation/routes/invoice.py:77-146` (final variant at issuance), `implementation/services/exposure.py:27-45` (both legs), plus the read-path recompute `core.py:44-46`.
   - (c) No edit: each behavior is pinned verbatim — §3.8 line 162 ("`CLEARED → REJECTED` — a clearance can be revoked"), §3.4 line 134 (acceptance check order, no customs gate), §2.8 line 96 ("clearance status *at the moment of issuance*"), §2.7 line 90 and §3.9 line 170 (order leg leaves committed, invoice leg joins both). Implementation matches all four exactly.

5. **§3.14 substitution price cap, inclusive boundary** (test_11 `test_substitution_price_cap_boundary`)
   - (a) Subject: cap formula `round_half_up(base_price_cents * 115 / 100)` and boundary inclusivity.
   - (b) Paths enumerated: `implementation/routes/quotation.py:149-157` (cap check, `>` fails ⇒ inclusive), its shared use by both create (`:194-221`) and revise (`:273-300`) via `_validate_quotation_lines`; `implementation/services/money.py:5-18` (round-half-up); PRD §3.14 line 204 and §2.5 line 82.
   - (c) No edit: PRD pins formula and "The boundary is inclusive — a substitute priced exactly at the cap passes" verbatim, and §2.5 pins half-up rounding for the cap. Test failure was a downstream effect of item 1's fixture bug (line-level `allows_substitution` stuck `False` → correct `ERR_SUBSTITUTION_NOT_ALLOWED`).

**Flakiness item:** `test_full_quantity_yields_delivered` sweep-2 `ConnectionError` — adjudicated infrastructure; no PRD or implementation relevance.

## Step 9: Complete PRD — 2026-08-14T11:58:49.573Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1700_ship_chandlery_vessel_provisioning/workspace/PRD_COMPLETED.md` produced as a minimal patch over the latest PRD.

**Source vs output**: `PRD_FINALIZED.md` (319 lines / 49,003 chars) → `PRD_COMPLETED.md` (319 lines / 56,342 chars; +7,339 chars). 33 paragraphs touched, all in-paragraph inserts/revisions; no new sections or paragraphs.

**Counts**: 27 ambiguity-pins, 6 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — insert — ambiguity — unrecognized role strings get `ERR_INSUFFICIENT_PERMISSIONS` even on all-roles endpoints — middleware.py:64-73
- §2.2 — insert — ambiguity — `api_request_timestamp` is a wall-clock request-receipt stamp, not the logical clock — response.py:28-33
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` fall back to defaults/clamp (never error); `has_more` ⟺ `offset+limit < total_count` — response.py:41-46, 60-80
- §2.4 — revise — **mismatch** — entity/logical-clock timestamps emitted at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`), not three fractional digits; 3-digit form only on envelope meta — db.py:33-47
- §2.4 — insert — ambiguity — clock endpoint: missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/core.py:29-36
- §2.6 — insert — ambiguity — expected-version field mandatory; missing/non-integer → `ERR_INVALID_REQUEST` — services/validate.py:45-52
- §2.7 — insert — ambiguity — exposure recompute is a derived refresh: no `version`/`updated_at` bump, also applied on agent read — services/exposure.py:27-45, routes/core.py:44-47
- §2.8 — insert — ambiguity — pins the shared line formula: base = qty×price; duty = round-half-up(base×pct/100) unless duty-free; cold surcharge = qty × cold_rate(h), cold_rate = 5h cents/unit up to 72h, 5×72+12×(h−72) beyond (72 inclusive); line_total = base+duty+cold — services/pricing.py:20-75
- §3.1 — insert — ambiguity — negative `credit_limit_cents`/`payment_terms_days` → `ERR_INVALID_REQUEST` — routes/core.py:57-58
- §3.1 — insert — ambiguity — vessel-call `agent_id` must exist → `ERR_AGENT_NOT_FOUND` — routes/core.py:113-115
- §3.1 — insert — ambiguity — `base_price_cents` < 1 → `ERR_INVALID_REQUEST`; negative `duty_rate_pct` → `ERR_INVALID_REQUEST`; rate may be fractional — routes/catalog.py:33-40
- §3.2 — insert — ambiguity — `capacity_qty` required non-negative on all tiers (`ERR_INVALID_REQUEST`); `catalog_item_id` must exist (`ERR_CATALOG_ITEM_NOT_FOUND`) — routes/catalog.py:79-90
- §3.2 — insert — ambiguity — adjustment OCC check fires before quantity bounds — routes/catalog.py:139-148
- §3.3 — insert — ambiguity — requisition line FK → `ERR_CATALOG_ITEM_NOT_FOUND`; `requested_qty` < 1 → `ERR_INVALID_QTY` — routes/requisition.py:27-32
- §3.3 — insert — ambiguity — recall leaves `submitted_at` (restamped on resubmit); live-quotation check fires before state check — routes/requisition.py:102-127
- §3.4 — insert — ambiguity — quotation line FK errors; `qty` < 1 → `ERR_INVALID_QTY`, `unit_price_cents` < 1 → `ERR_INVALID_REQUEST` — routes/quotation.py:66-77
- §3.4 — insert — ambiguity — quotation also carries `provisional_subtotal_cents`/`provisional_rebate_cents`, refreshed on send/revise — routes/quotation.py:212-214, 261-263, 295-297
- §3.4 — insert — ambiguity — send also requires requisition still `SUBMITTED`/`QUOTED` (`ERR_REQUISITION_NOT_OPEN_FOR_QUOTES`) — routes/quotation.py:256-258
- §3.4 — revise — **mismatch** — lazy expiry scoped to attempts passing the state precondition; state-ineligible attempts surface the state error without flipping to `EXPIRED` — routes/quotation.py:250-255, 279-282, 310-313
- §3.4 — insert — ambiguity — revise: expiry check between state check and OCC comparison — routes/quotation.py:279-286
- §3.4 — insert — ambiguity — accept: officer-ownership check positioned between validity window and IN_PORT gate — routes/quotation.py:312-321
- §3.4 — insert — ambiguity — credit gate pinned: rejects iff quotation's current `provisional_total_cents` strictly exceeds `credit_limit_cents − committed_exposure_cents` (recomputed at accept); equality passes — routes/quotation.py:323-328
- §3.6 — revise — **mismatch** — delivery scheduling is not gated on order fulfillment status (was "With an order open") — routes/order_delivery.py:100-107
- §3.6 — insert — ambiguity — scheduling gate order: body/FK → customs → window sanity → containment → qty floor (`ERR_INVALID_QTY`) → qty cap; item-not-on-order → `ERR_QTY_EXCEEDS_REMAINING` — routes/order_delivery.py:109-165
- §3.6 — insert — ambiguity — confirm: negative `qty` → `ERR_INVALID_QTY`; unplanned item → `ERR_QTY_EXCEEDS_REMAINING`; body validated before state — routes/order_delivery.py:223-256
- §3.7 — insert — ambiguity — arrive transition: only from `SCHEDULED` (`ERR_VESSEL_CALL_NOT_ARRIVABLE`), stamps `actual_eta`, moves to `IN_PORT` — routes/core.py:147-158
- §3.8 — insert — ambiguity — customs restatement check fires before port-presence check — routes/core.py:233-238
- §3.9 — insert — ambiguity — `fx_rate_to_settlement` missing/non-numeric → `ERR_INVALID_REQUEST`; non-positive → `ERR_INVALID_FX_RATE` — routes/invoice.py:84-86
- §3.10 — insert — ambiguity — check order ownership → body → state → currency/fx → tolerance; `amount_cents` < 1 → `ERR_INVALID_QTY`; payment record stores fx rate (null when currencies match) and `writeoff_applied_cents` (0 non-closing) — routes/invoice.py:176-242
- §3.10 — revise — **mismatch** — delta redefined as this payment's `converted_amount_cents` minus pre-payment `outstanding_cents` (previously read as paid+converted minus outstanding) — routes/invoice.py:213-230
- §3.12 — insert — ambiguity — complaint on non-`DELIVERED` delivery → `ERR_INVALID_REQUEST`; ownership checked first; `rejected_qty` < 1 → `ERR_INVALID_QTY`; line FK → `ERR_CATALOG_ITEM_NOT_FOUND` — routes/complaint.py:50-72
- §3.12 — insert — ambiguity — successful accept moves complaint to `ACCEPTED`; review gate order: state → four-eyes → creditable-invoice selection — routes/complaint.py:108-114, 164
- §3.13 — revise — **mismatch** — `CREDITED` flip only when outstanding lands exactly on zero with credit standing; an overshooting application drives outstanding negative and leaves invoice `ISSUED`/`PARTIALLY_PAID` — routes/invoice.py:41-57
- §3.13 — insert — ambiguity — revocation re-derives status generally: an invoice that reached `PAID` after the credit was applied returns to `PARTIALLY_PAID`, never `PAID` — routes/invoice.py:41-57, routes/complaint.py:264-274
- §3.14 — revise — **mismatch** — bonded parity is symmetric (bonded original → non-bonded substitute also inadmissible) and evaluated before the admissibility tests — routes/quotation.py:100-111
- §4 — insert — ambiguity — nested list endpoints 404 with the parent's `ERR_*_NOT_FOUND`; unmatched paths/methods → `ERR_INVALID_REQUEST` (400) — app.py:32-42

**Note**: current results.json shows 86/91 tests passing; the 5 failures are test-side issues (two `NameError`s, two setup-ordering mistakes around the customs gate, one expectation conflicting with bonded parity) — per the brief, tests were treated as auxiliary only and no behavior was taken from them.

Orchestrator note on the Step 9 "results.json" remark: the 86/91 figure came from a stale artifact of Step 6's dry run, not the post-Step-7 state. The authoritative final sweep artifacts are `workspace/implementation/results.{1..8}.json`, each verified passed=91 total=91 failed=0 (copied from `/tmp/task1700_results/` after Step 7's clean sweep 4). Neither implementation/ nor test code was modified during Steps 8–9, so the 8×91/91 result stands.

## Cleanup — 2026-08-14T11:59:56.584Z

Removed stale `workspace/results.json` (mtime 2026-08-14 10:59, passed=86/91) — a leftover of Step 6's pre-fix dry run that misrepresented the final state. The authoritative final-sweep artifacts remain at `workspace/implementation/results.{1..8}.json` (8 × 91/91).

Pipeline complete: Steps 1–9 all done. `workspace/PRD_COMPLETED.md` exists.
