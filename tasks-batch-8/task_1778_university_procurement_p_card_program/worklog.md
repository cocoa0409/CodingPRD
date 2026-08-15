# Worklog — task_1778_university_procurement_p_card_program

## Step 1: Create Task Directory — 2026-08-14T15:32:00.000Z

Task directory `tasks/task_1778_university_procurement_p_card_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation args. Requested difficulty: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-14T16:14:24.177Z

Scaffold generation complete for `task_1778_university_procurement_p_card_program`. All three files are written and `scaffold_lint.py` reports a clean verdict.

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/SCAFFOLD.yaml` | 2,086 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,583 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/SCAFFOLD_CORNER_DESIGN.yaml` | 2,165 |

## Counts

- **Entities: 15** — Department, Vendor, Grant, Contract, Requisition, ApprovalRecord (append-only audit, `common_fields: false`), BidSolicitation, Quote, PurchaseOrder, Receipt, Invoice, PCard, LimitElevation, PCardTransaction, SurplusAsset
- **State machines: 13** (all entities except Department and ApprovalRecord)
- **Calculation rules: 12** — incl. dual variants (grant ledger provisional-vs-settled; diversity committed-vs-paid), pinned-order grant F&A charge, per-line-then-sum three-way-match rounding, weighted award scoring with deterministic selector, rolling anti-split aggregate, proceeds waterfall, cycle aging
- **Validation rows: 12** priority tiers (auth → role → existence → ownership → OCC → lifecycle state → safety/SoD → temporal → constraint → referential → fiscal → shape)
- **Endpoints: 83** (incl. `POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`)
- **Error catalog: 88** codes
- **Roles: 11** — segregation-of-duties model; Cardholder is `entity_backed:PCard` (X-User-ID == card id), all others opaque
- **Concurrency rules: 3** OCC rules (`requisition-edit-stale-version`, `contract-amend-stale-version`, `pcard-limit-stale-version`), all 412/ERR_STALE_VERSION
- **§1.8 difficulty instances: 25** — dual_variant_calc 2, combinatorial_formula 3 (one per mode a/b/c), non_linear_state_machine 3 (Requisition cycle, Contract negotiation cycle, PO parallel dimensions), transitive_cascade 3 (contract-terminate depth-3, vendor-suspend depth-4, cycle-close depth-3), priority_pair_validation_conflict 3 (state/fiscal, safety/referential, existence/state), boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2 (half-open contract exclusivity vs 7-day-buffer elevation windows), compensating_invariant 3 (grant budget decomposition, card credit decomposition, proceeds waterfall)
- **§1.9 corner instances: 46 entries = 40 active + 6 `excluded_because` stubs** — entities 5, state_machines 8, calculations 5, validations 7, endpoints 4, errors 5 (+6 stubs), rbac 2, cross_cutting_layers 3, consistency_model 1

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(83 endpoints, 15 entities, 25 §1.8 + 40 §1.9 instances, 728 calls scanned, exit 0)

## Design decisions downstream steps must know

1. **Grant charge vs invoice amount differ deliberately.** Encumbrance and settlement use `charge_cents = total + round_half_up(F&A × (total − equipment_excluded))`; the invoice matches only direct amounts. Equipment exclusion is **strictly `unit_price_cents > equipment_cap_cents`** (== cap is not excluded).
2. **Approval chain is a pinned snapshot** computed at submit with exact order `[DEPARTMENT, GRANT_COMPLIANCE?, SOLE_SOURCE?, PURCHASING?, DIRECTOR?, CONTRACT_REVIEW?]`, inclusive thresholds ($5k/$25k/$100k). The PURCHASING step has a sourcing gate (award, executed contract, or approved sole source). The chain is **recomputed on every resubmit** after RETURNED.
3. **PO has parallel dimensions**: `fulfillment_status` (receipts) × `match_status` (derived from invoices + `contract_terminated_flag`). Receipt void re-matches PAYABLE invoices; contract termination flags open POs.
4. **Match rounding order is pinned**: round each per-line tolerance (2% × PO price × qty) to integer cents, THEN sum. The §1.8 instance pins the 11-vs-10 cent divergence literally.
5. **P-card utilization keeps DISPUTED debits in**, drops REVERSED, and is **scoped to current `cycle_index`** — close-cycle resets utilization while old unreconciled debits persist and age the suspension counter (suspend at ≥2 consecutive dirty cycles, cascading to cancel SCHEDULED elevations).
6. **CREDIT transactions post directly to RECONCILED**; DISPUTED resolves back to `pre_dispute_status` (merchant favor) or REVERSED with grant-spend compensation (cardholder favor).
7. **All temporal semantics run on the logical clock** (deadlines, 30-day anti-split window on `submitted_at`, 10-day redistribution window on `declared_at`, contract half-open periods, elevation windows) — wall clock `created_at` is used only as the final award tie-break, never `id`.
8. **OCC is the only write-write mechanism**; the amend endpoint both creates the superseding draft AND bumps the original contract's `version` (the true create-with-supersede race), and the supersede target is excluded from the contract-overlap check at execute.
9. **Anti-splitting**: rolling [clock−30d, clock] sum over same dept+vendor requisitions in {SUBMITTED, APPROVED, PO_ISSUED} + this total, inclusive `>=` 2,500,000 trigger, contract-riding requisitions exempt.
10. **Unknown/extra request fields are ignored** (lenient input), and the §1.9 create instance asserts smuggled `total_cents`/`status` are discarded; one-open-invoice-per-PO and PAID-closes-invoicing rules (`ERR_PO_INVOICING_CLOSED`) keep invoice multiplicity deterministic.

## Step 3: Copy Shared Files — 2026-08-14T16:14:24.177Z

Copied `./INSTRUCTION.md` → `tasks/task_1778_university_procurement_p_card_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:27:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Summary

**PRD line count:** 417 lines.

### Section map (heading → entity/rule coverage)

- **§1 Introduction** (2 paragraphs) — program scope, design goals (determinism, auditability, segregation of duties, logical clock).
- **§2.1 RBAC** — `X-User-ID`/`X-User-Role`; all 11 roles named; identity prose per role (Cardholder entity-backed by `PCard`, ten opaque roles); `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, `ERR_FORBIDDEN_ROLE`, and the high-value-sale exception to it.
- **§2.2 API Response Structure** — verbatim canonical block (byte-compared equal to `section-2.2-response-structure.md`).
- **§2.3 Pagination** — `limit` (default 10, 1–100), `offset` (default 0, non-negative), `ERR_INVALID_PAGINATION_PARAMETERS`, `created_at` ascending sort, meta fields, list-filter parameter names.
- **§2.4 Logical Clock** — initial `2026-08-01T00:00:00Z`, admin-only set capability, `to_iso8601`/`current_utc`, no entity mutation.
- **§2.5 Common Resource Properties** — `id`/`created_at`/`updated_at`/`version` semantics; ApprovalRecord as the sole exception (only `id` + `created_at`).
- **§2.6 Money, Precision, Rounding** — integer cents; round-half-up points (grant indirect, per-line tolerance, dept share, sale floor, 2-decimal scores, 4-decimal ratios).
- **§2.7 OCC** — all three concurrency rules with exact `expected_*_version` fields, `ERR_STALE_VERSION` (412), and the "no version field elsewhere" clause.
- **§2.8 Validation Priority Order** — all 12 priority rungs in order, with the full lifecycle-409 family and the shape-last note.
- **§2.9 Existence/Reference Resolution** — left-to-right path validation; all 14 `ERR_*_NOT_FOUND` codes; flat-graph FK narrative; reverse-reachability reads.
- **§2.10 Cascades/Derived Reconciliation** — atomic immediate cascades, version/updated_at bumps on server-initiated mutations, PO parallel status dimensions.
- **§3.1** — Department, Vendor (+ suspension cascade/reinstate), Grant (+ ledger: `spent_cents`, `encumbered_cents`, both remaining variants, conservation invariant; close-guard).
- **§3.2** — Contract full lifecycle, negotiation loop/round counter, execute quadruple gate (incl. overlap exclusivity + supersede), amend OCC + version bump, terminate triple cascade.
- **§3.3** — Requisition create/edit/submit/resubmit/cancel; chain resolution with inclusive $5k/$25k/$100k thresholds; grant-charge pinned calculation; anti-splitting 30-day inclusive window (equality triggers); step-role map; DEPARTMENT limit gate; PURCHASING sourcing gate; final-step `ERR_GRANT_BUDGET_EXCEEDED` (402) + encumbrance attach; ApprovalRecord audit shape.
- **§3.4** — BidSolicitation guards, Quote rules, close scoring (70/20/10 weights, pinned min-price, 2-decimal round), award pool/winner/tie-break/override rules, cancel + cascade-only AWARDED→CANCELLED.
- **§3.5** — PO issue (pinning, `contract_version_pinned`, requisition → `PO_ISSUED`), match_status derivation, receipts + over-receipt guard, void recompute + PAYABLE re-match to `RECEIPT_VOIDED`, PO cancel (encumbrance release, requisition reverts to `APPROVED`).
- **§3.6** — Invoice creation gates, full three-way match (2% per-line tolerance rounded before summing, precedence `NO_RECEIPT` > `QTY_OVER_RECEIPT` > `PRICE_VARIANCE`, aggregate rule), resolve-exception both actions + self-resolution ban, pay + grant settlement.
- **§3.7** — PCard issuance + `ERR_LIMIT_INCONSISTENT`, OCC limits change, cardholder identity, transaction posting gates (MCC, single/monthly inclusive), effective-limit boundary behavior, utilization formula + invariant.
- **§3.8** — Reconcile (incl. GRANT allowability gauntlet + spend booking), dispute/`pre_dispute_status`, both resolve outcomes + grant compensation, card admin transitions, close-cycle aging (inclusive 2-cycle suspension), elevation overlap/7-day-gap rules.
- **§3.9** — SurplusAsset full lifecycle, 10-day redistribution window (both temporal errors), claim self-ban, sale floor (`max(2500, round_half_up(0.40 × estimated))`), ≥$50k director gate, proceeds waterfall with central-remainder conservation, donate/scrap.
- **§3.10** — Diversity report: `COMMITTED` (default) vs `PAID` bases, optional inclusive `window_start`/`window_end`, 4-decimal ratio, 0.0000 on zero spend, `goal_met` vs `diversity_goal_pct`.
- **§4** — 83-row endpoint table (Method/Path/Description/Roles only) + status-code paragraph (201 create / 200 modify).
- **§5** — 88-row error table (Error ID / HTTP Status only).

### Coverage audit

- **§1.5 endpoints:** all 83 present in the §4 table with correct method, path, and role set (mechanically verified against the scaffold). Gaps: none.
- **§1.6 error codes:** all 88 IDs appear in §2/§3 prose near their triggers (mechanically verified; §5 carries IDs + statuses only). Gaps: none.
- **§1.7 roles:** all 11 role names spelled exactly in §2.1 with identity semantics translated (Cardholder → `entity_backed:PCard`; ten opaque roles named individually, with recorded-field ownership comparisons explained). Gaps: none.
- **Field-name coverage (Contract 1):** 130 required names (all entity fields, request-body keys, query params, common fields) — 130 present, 0 missing (two-pass mechanical check; `po_id`, `solicitation_id`, `VOIDED`, `COMMITTED` were caught and repaired).
- **Rule coverage (Contract 2):** 12/12 priority rungs; 3/3 OCC rules (endpoint + expected-version field + `ERR_STALE_VERSION`/412); 60+ state transitions all with preconditions/side effects (incl. sibling branches: resubmit, all three cancel sources, both dispute-resolution sub-branches, both resolve-exception actions, both ledger/report variants); 11/11 calculations in precise reconstruction-safe prose (constants embedded: 500000/2500000/10000000 cents, 2%, 70/20/10, 0.40/2500/5000000, 0.50, 30-day window, 2 cycles, 7-day gap, 10-day window); every endpoint side effect expressed. No pseudocode operators; one fuzzy word ("conservatively") found and removed.
- **§3 path purity (Contract 3):** 692 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS.
- **§2.2:** verbatim (byte-identical after heading-split comparison).

### Zero-Silence Rule self-check

No knowingly under-determined behavior remains. Two spots are faithful compressions worth flagging: (1) for `POST /contracts/{id}/amend`, the scaffold names no distinct error when the amendment target is not `EXECUTED`, so the PRD states the `EXECUTED` requirement without attaching a new error code (the supersede-target check at execute time does carry `ERR_CONTRACT_STATE_INVALID`, and is stated); (2) null-unless-set defaults for outcome fields (`claiming_department_id`, `sale_price_cents`, `buyer_name`, `recipient_name`) are expressed via "recorded at the event" phrasing rather than an explicit "null otherwise" clause — reconstructible but implicit. Receipt `POSTED` initial status is implied by the posting act and the void precondition rather than asserted with the word "initial". Everything else — defaults, thresholds, boundary inclusivity, cascades, invariants, and reason precedence — is stated explicitly.

## Step 5: Generate Unit Tests — 2026-08-14T17:05:00.000Z

Generation complete. Summary:

## Files written

**test_helpers/ (1,812 lines)**
- `types.py` (457) — 11-role `UserRole` enum, all status/step/category enums, TypedDicts for all 15 entities; `ApprovalRecord` carries only `id` + `created_at` (common_fields: false honored)
- `api_client.py` (344) — `ApiClient(GenericApiClient)` with one method per endpoint (74 methods covering clock, departments, vendors, grants, contracts, requisitions, solicitations/quotes, POs/receipts/invoices, P-cards/elevations/transactions, surplus)
- `api_errors.py` (200) — full 82-entry `ApiErrorId` catalog + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (195) — per-entity assertions + `assert_grant_ledger_conservation`, `assert_card_credit_invariant`, `assert_proceeds_conservation`
- `factories.py` (149) — payload factories with a sequence counter; grant/contract defaults keep the 2026-08-01 default clock inside all periods
- `constants.py` (52) — all thresholds (T1/T2/T3, bid threshold, match tol, weights, suspend-after, floors, gaps, windows)
- `test_users.py` (46) — shared headers for all 11 roles with SoD-safe operator ids; `make_cardholder_headers(pcard_id)` for the entity-backed Cardholder identity
- `fixtures.py` (334) — composite helpers: `create_executed_contract`, `create_and_submit_requisition`, `walk_approval_chain` (reads live chain, dispatches step→role headers), `create_approved_requisition`, `create_po`, `create_po_fully_received`, `create_payable_invoice`, `create_competitive_requisition`, `create_open_solicitation`, p-card debit/reconcile helpers, `create_declared_asset`/`create_listed_asset`, `read_ledger`
- `__init__.py` (35) — barrel export

**test_suite/ (3,876 lines, 90 tests, 15 files + conftest)** — all collected cleanly by pytest; zero skip/xfail markers; every docstring carries verbatim PRD citations (machine-verified against PRD.md, 90/90 pass) and ends with exactly one resolving `Design:` tag (machine-verified against both yamls).

## Coverage

**Queue A (difficulty): 25/25 instances translated, 0 skipped — 50 tests (exactly 2 per instance).** The three `priority_pair_validation_conflict` instances were kept because PRD §2.8 explicitly defines the rung ladder ("a failure on an earlier rung prevents any later rung from being evaluated") with per-rung error families — both filter conditions pass.

**Queue B (corner): 40/40 non-stub instances translated, 0 skipped — 40 tests.** All 6 `excluded_because:` stubs verified to resolve to real queue-A instances and were not translated.

## Notable decisions for the Step 7 diagnostic loop

1. **Corrected expected values in one corner instance.** `Corner/calculations/diversity_report_excludes_cancelled_and_rejected` pre-computes COMMITTED as diverse 0 / total 600,000 / ratio 0.0000, but its own PO-C (diverse vendor, 200,000, FULLY_RECEIVED — invoice REJECTED but PO never CANCELLED) remains in the committed set per both PRD §3.10 ("purchase orders whose fulfillment is anything other than `CANCELLED`") and the scaffold formula. The test asserts the PRD-derived values: COMMITTED diverse 200,000 / total 800,000 / ratio 0.2500 / goal_met true; PAID 0 / 600,000 / 0.0000. This is the one place the YAML's literal numbers were not copied — copying them would fail a correct implementation.
2. **Version assertions are relative, never absolute** (PRD §2.5 does not pin the initial version). Tests use `assert_version_incremented` or captured-version equality (e.g., `contract_version_pinned == version captured from the execute response`), not literal `version == 4/6`.
3. **`walk_approval_chain`** is the workhorse — it GETs the requisition and approves each pinned step with that step's role, so fixtures are robust for any chain composition; role identities (`dept-approver-1`, `buyer-1`, etc.) never equal `req-user-1`, so SoD never trips in setup.
4. **Cardholder calls always thread the real card id** via `make_cardholder_headers(card["id"])` (the PRD's entity-backed identity rule).
5. Clock-sensitive tests call `set_clock` explicitly; factories' default grant/contract periods contain the 2026-08-01 default clock so non-temporal tests never accidentally expire.

## Step 6: Generate Implementation — 2026-08-14T17:05:00.000Z

All done. The implementation is complete and verified. Here's the full summary:

## Implementation Summary — task_1778 (University Procurement & P-Card Program)

### Files written (all under `.../workspace/implementation/`, 3,262 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op once Flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 71 | Flask entry, blueprint registration, error handlers |
| `db.py` | 121 | In-memory store (15 dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`), UUIDs, `_seq` ordering, RQ-/PO- number minting |
| `errors.py` | 122 | `ApiError` + all 88 catalog IDs |
| `response.py` | 44 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; pagination fields in `meta` |
| `middleware.py` | 57 | p1 header check (11 roles) + p2 role-set authorization |
| `util.py` | 257 | ISO parsing, Decimal round-half-up helpers, lenient shape validation, typed-404 FK resolution, `limit`/`offset` pagination |
| `services.py` | 492 | All calculations, derived fields, cascades |
| `routes/` | 13 modules, 2,126 lines | clock, departments, vendors, grants, contracts, requisitions, solicitations, purchase_orders, invoices, pcards, pcard_transactions, surplus |

### Coverage
- **Endpoints: 83/83** of the PRD §4 table implemented and exercised.
- **State machines: 13/13** — Vendor, Grant, Contract (incl. negotiation loop, supersede, terminate cascade), Requisition (cyclic submit/return/resubmit, approval chain, cancel, issue), BidSolicitation, Quote (system transitions), PurchaseOrder (parallel fulfillment/match dimensions), Receipt (void re-match), Invoice, PCard (incl. close-cycle escalation), LimitElevation, PCardTransaction (dispute/`pre_dispute_status` restore), SurplusAsset.
- **Calculations: 12/12** — requisition_total, approval_chain_resolution (inclusive tiers 500k/2.5M/10M), grant_charge (strict `>` cap, single round-half-up), grant_budget_ledger (provisional/settled, conserved), three_way_match (per-line tolerance rounding before summation; reason precedence NO_RECEIPT > QTY_OVER_RECEIPT > PRICE_VARIANCE; aggregate rule), award_score (70/20/10, pinned min-price at close, tie-break submitted_at→created_at, never id), pcard_utilization (cycle-scoped, DISPUTED kept, REVERSED dropped, credits negative), effective_single_txn_limit (half-open elevation window), reconciliation_aging (inclusive ≥2 suspension), diversity_spend_ratio (committed/paid, 4dp, 0.0000 on zero), anti_split_aggregate (inclusive 2.5M rolling 30-day), surplus_proceeds_waterfall (central absorbs rounding remainder).
- **OCC: 3/3** rules (`expected_requisition_version`, `expected_contract_version`, `expected_pcard_version` → `ERR_STALE_VERSION` 412).
- **Storage**: process-local dicts per collection; empty at every boot, zero seeding; derived figures (grant ledger, card utilization, PO match_status) computed at read time from source data — drift-proof by construction; version bumps only on stored-field mutations (cascade-affected resources each get their own touch).

### Verification
- `prd-bench-local-run --isolation per-test-server`: **89/90 passing, stable across two full runs**; plus two hand-written end-to-end smoke suites (≈190 assertions) replaying every §1.8/§1.9 design fixture, all passing.
- Sole failure: `test_post_award_suspension_unwinds_award_chain` — a **generator inconsistency**: the §1.8 design suspends V2 pre-close (making V4 the winner), but the generated test omits that suspension while keeping V4 as the expected winner. With all four quotes eligible the PRD formula must award V2 (lowest price ⇒ score 70.00). Verified live that the server follows the PRD exactly; "fixing" it would break three other award tests. Left PRD-faithful.

### PRD interpretation decisions (candidate Step 8/9 patch sites)
1. **Contract-termination cascade scope** — SCAFFOLD §1.2/PRD §3.2 say POs in {ISSUED, PARTIALLY_RECEIVED} get flagged; the §1.8 instance pins a FULLY_RECEIVED PO getting flagged. Implemented as all non-CANCELLED POs.
2. **issue-po vendor presence** — PRD §3.5 names `ERR_SOURCING_REQUIRED` when vendor is missing; generated fixtures issue POs from vendor-less requisitions and expect success. Check omitted (gate remains at the PURCHASING step, as pinned).
3. **Grant close guard order** — encumbrance check fires before the ACTIVE-state check (test closes a SUSPENDED+encumbered grant expecting `ERR_GRANT_HAS_OPEN_ENCUMBRANCES`).
4. **Pre-submit chain fields** — `required_chain=[]`, `current_step_index=0` at creation (test schema requires list/int; PRD prose says "computed at submit").
5. **Timestamps** — `created_at`/`updated_at`/meta use wall clock (award tie-break 2 is explicitly "wall"); all rule stamps use the logical clock.
6. **Validation orderings where PRD ladder and §3 narrative diverge** — ladder (§2.8) followed: execute checks overlap (p9) before vendor-active (p10); issue-po checks expiry (p8) before EXECUTED (p10); submit's below-threshold sole-source 400 evaluated last; request-body shape evaluated between p6 and p7 (the "never a business error for a malformed body" hard rule).
7. **ACCEPT_VARIANCE failed re-match** — invoice stays EXCEPTION with recomputed reason/totals (derived-field recomputation reading of "stays in EXCEPTION").
8. **Receipt-void re-match evaluates quantity only**; surviving invoices keep their original totals.
9. **Award with named quote** — quote on another solicitation → scoped `ERR_QUOTE_NOT_FOUND`; named quote outside the eligible pool → `ERR_AWARD_NOT_TOP_SCORE` even with override (invented; unpinned).
10. **Lenient input** — unknown/smuggled body fields ignored (corner-pinned); empty lines allowed at create (submit's non-empty/positive gate kept live); unknown receipt `line_no` → 400 `ERR_INVALID_REQUEST`; amend on non-EXECUTED → `ERR_CONTRACT_STATE_INVALID` (no distinct code named); elevation create/close-cycle on CLOSED card → `ERR_CARD_CLOSED`; close-cycle allowed on SUSPENDED; scores are null when the at-close eligible pool is empty; cascade returns append no ApprovalRecord; `min_quotes` must be ≥1; no `requester_id == X-User-ID` equality check at requisition create (input-sourced field).

## Step 7: Run Tests and Iterate — 2026-08-14T17:20:00.000Z

**Summary**

- **Iterations run:** 2 (sweep 1: 8 rounds × 89/90 with one consistent failure; fix applied; sweep 2: 8 rounds × 90/90, all clean — exit condition met).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/test_suite/test_06_solicitations_and_awards.py` — `TestVendorSuspensionAwardUnwind::test_post_award_suspension_unwinds_award_chain`: added the design-prescribed pre-close suspension of non-winner vendor V2 (`api.suspend_vendor(vendors["V2"]["id"], {"reason": "debarment review"}, ADMIN_H)`) before advancing the clock and closing the solicitation. Why: the test asserted V4's quote wins the award, but with all four quotes eligible the PRD §3.4 scoring formula (70/20/10, min eligible price 2,900,000) must award V2 at 70.00 vs V4's 67.67. The §1.8 design instance `vendor_suspension_award_unwind_cascade` (SCAFFOLD_DIFFICULTY_DESIGN.yaml lines 660–763) prescribes the V2 pre-close suspension as trigger step 1 (making min eligible price 3,000,000 → V4 scores 70.00 and wins); the generated test omitted that step while keeping V4 as expected winner. The asserted rule itself (§3.1 post-award suspension cascade: awarded quote → DISQUALIFIED, AWARDED solicitation → CANCELLED, SUBMITTED requisition → RETURNED/`VENDOR_SUSPENDED`) is PRD-verbatim and uniquely derivable, so this was a STEP 2 test-setup fix, not a deletion. The fix mirrors the sibling test `test_pre_close_suspension_shrinks_eligible_pool`, which already performs this exact suspension and passed in every round.

- **Fixes applied to `implementation/`:** none. The implementation was verified PRD-faithful: the failure detail (`assert awarded["awarded_quote_id"] == quotes["q4"]["id"]` mismatch) showed the server correctly awarding per the PRD §3.4 formula, and the worklog's prior live verification was independently confirmed against `services.py::vendor_suspension_cascade` and `routes/solicitations.py` scoring/award code.

- **Diagnostics note:** interim per-test lines in the shared sweep stdout are unreliable under 8-way interleaving (in-flight test-name fragments glue onto other rounds' outcome fragments — sweep 1 showed phantom `test_solicitation_deadline_half_open_both_faces FAILED` lines). The junit-derived `results.${i}.json` files and per-round pytest summaries are authoritative and were consistent in all rounds of both sweeps.

## Step 8: Finalize PRD — 2026-08-14T17:35:00.000Z

Done. `PRD_FINALIZED.md` has been produced as an **identical copy** of `PRD.md` — the honest outcome, per the task's explicit guidance for this case.

## Verdict

The single Step 7 item is a **pure test-fixture bug** (a missing `api.suspend_vendor(V2, ...)` setup step in `test_post_award_suspension_unwinds_award_chain`). It reveals **no PRD silence and no PRD/implementation mismatch**:

- With all four quotes eligible at close, the PRD §3.4 formula uniquely determines V2 wins: min eligible price 2,900,000 → V2 price component 100 → score 70.00; V4 → 100×2,900,000/3,000,000 × 0.70 = 67.67. The implementation awarded V2 exactly as the PRD requires; the generated test's expected winner (V4) was only reachable via the design instance's prescribed pre-close V2 suspension, which the fixture omitted.
- The asserted cascade rule (awarded quote → DISQUALIFIED, AWARDED solicitation → CANCELLED, SUBMITTED requisition → RETURNED/`VENDOR_SUSPENDED`) is PRD §3.1 verbatim, and the sibling test `test_pre_close_suspension_shrinks_eligible_pool` (same suspension, passed every round) independently confirms implementation stability.

## Summary

- **Line counts / %-delta:** `PRD.md` 417 lines; `PRD_FINALIZED.md` 417 lines; **0% delta** (byte-identical, verified with `diff`).
- **Changes:** none — zero edits.

## Investigation log (no-edit decision record)

Subject identified for the single Step 7 item: **vendor suspension cascade + solicitation close-time scoring + award winner selection**.

Implementation paths enumerated and read (all consistent with existing PRD prose, so no wording change was warranted):

1. `implementation/services.py:355-377` — `compute_scores_at_close`: eligible pool pinned at close as SUBMITTED + vendor ACTIVE (matches §3.4 verbatim); weights `W_PRICE=0.70 / W_DIVERSITY=0.20 / W_SUSTAINABILITY=0.10` (services.py:17-19); `rhu_2dp` rounding applied once at the end (matches §3.4/§2.6).
2. `implementation/services.py:387-394` — `select_winner`: highest score, ties by earliest `submitted_at` then earliest `created_at` (matches §3.4 verbatim).
3. `implementation/services.py:401-427` — `vendor_suspension_cascade`: hop 1 SUBMITTED quotes on OPEN/CLOSED → DISQUALIFIED; hop 2 AWARDED quote → DISQUALIFIED + AWARDED solicitation → CANCELLED; hop 3 SUBMITTED requisition → RETURNED/`VENDOR_SUSPENDED` (all match §3.1 verbatim).
4. `implementation/routes/solicitations.py:86-150` — `close_solicitation` (deadline gate, score pinning at close) and `award_solicitation` (CLOSED gate, empty-pool/min_quotes/top-score gates, side effects: winner AWARDED, others NOT_AWARDED, requisition `vendor_id` + `sourcing_method=COMPETITIVE_BID`) — all match §3.4 verbatim.

Wording adjustment made: none — every enumerated path is already uniquely and verbatim determined by the current PRD text, so any edit would risk creating a new mismatch rather than fixing one.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T17:52:00.000Z

All edits applied and verified. The diff contains exactly the 32 intended hunks.

## Summary

**Source**: `PRD_FINALIZED.md` (identical to `PRD.md`) → `PRD_COMPLETED.md`
**Line counts**: 417 → 420 (+3 lines); **char delta**: 72,570 → 76,914 (+4,344 chars)
**Counts**: 28 ambiguity-pins, 5 mismatch-revisions (the 5 mismatches span 7 hunks; 32 diff hunks total, all in-paragraph inserts/revisions; no new sections).

### Ambiguity-pins (PRD silent → pinned to impl)
- §2.1 — insert — ambiguity — blank/whitespace headers count as missing — implementation/middleware.py:39-44
- §2.2 — insert — ambiguity — undefined path → `ERR_INVALID_REQUEST` 404; unsupported method → `ERR_INVALID_REQUEST` 400 — implementation/app.py:48-58
- §2.3 — insert — ambiguity — non-integer limit/offset also rejected; `created_at` ties broken by creation order — implementation/util.py:211-232, implementation/db.py:116
- §2.4 — insert — ambiguity — clock-set response echoes the supplied `to_iso8601` string verbatim as `current_utc` — implementation/routes/clock.py:18
- §2.5 — insert — ambiguity — `version` starts at 1; `updated_at` initialized equal to `created_at`; `created_at`/`updated_at`/`api_request_timestamp` use wall clock, only domain-event stamps use logical clock — implementation/db.py:93-106, implementation/response.py:13
- §2.8 rung 12 — insert — ambiguity — unknown/system-managed client fields ignored; explicit null = absent unless a workflow says otherwise; no range checks beyond named rules — implementation/util.py:165-181
- §3.1 — insert — ambiguity — vendor-suspend `reason` accepted but not recorded — implementation/routes/vendors.py:74
- §3.1 — insert — ambiguity — disputed-after-reconcile grant debits remain in `spent_cents` until resolution — implementation/services.py:176-184
- §3.2 — insert — ambiguity — negotiate `note` accepted but not recorded — implementation/routes/contracts.py:97
- §3.2 — insert — ambiguity — amendment `value_cents`/`terms_text` default to the amended contract's current values when omitted — implementation/routes/contracts.py:184-187
- §3.2 — insert — ambiguity — termination requires a non-empty `reason` — implementation/routes/contracts.py:205
- §3.3 — insert — ambiguity — at creation `required_chain`=[], `current_step_index`=0, `charge_cents`=null; `returned_reason` retained through edits/resubmissions — implementation/routes/requisitions.py:103-109
- §3.3 — insert — ambiguity — edit: explicit null clears `vendor_id`/`grant_id`/`contract_id`/`sole_source_justification`; null `lines` treated as absent; `has_grant_funding` re-derived on every edit — implementation/routes/requisitions.py:157-163
- §3.3 — insert — ambiguity — return requires a non-empty `reason` — implementation/routes/requisitions.py:318
- §3.4 — insert — ambiguity — `min_quotes` must be ≥1; `response_deadline` not validated against the clock at creation — implementation/routes/requisitions.py:361-364
- §3.4 — insert — ambiguity — close with no eligible quotes leaves every `score` null — implementation/services.py:365-369
- §3.4 — insert — ambiguity — naming a quote outside the eligible pool → `ERR_AWARD_NOT_TOP_SCORE` even with `override_reason` — implementation/routes/solicitations.py:130-131
- §3.5 — insert — ambiguity — receipt `line_no` not on the order → `ERR_INVALID_REQUEST` — implementation/routes/purchase_orders.py:96-98
- §3.6 — insert — ambiguity — invoice `total_cents` = integer sum of quantity × unit price over its lines — implementation/routes/purchase_orders.py:180
- §3.6 — insert — ambiguity — ACCEPT_VARIANCE re-match refreshes `total_variance_cents`/`total_tolerance_cents`/`exception_reason` even when it fails — implementation/routes/invoices.py:61-70
- §3.7 — insert — ambiguity — limits change accepts any subset of the three fields (including none); null `allowed_mccs` leaves the list unchanged — implementation/routes/pcards.py:105-113
- §3.8 — insert — ambiguity — GENERAL allocation ignores client-supplied `grant_id`/`cost_category`, both stored null — implementation/routes/pcard_transactions.py:161-162
- §3.8 — insert — ambiguity — dispute `reason` accepted but not recorded; `pre_dispute_status` cleared on either resolution outcome — implementation/routes/pcard_transactions.py:181-185,198-205
- §3.8 — insert — ambiguity — elevation scheduling refused only on `CLOSED` cards; `SUSPENDED` cards accept new windows — implementation/routes/pcards.py:198-199
- §3.8 — insert — ambiguity — close-cycle checkpoint runs on `ACTIVE` or `SUSPENDED`, refused only on `CLOSED` — implementation/routes/pcards.py:166-167
- §3.9 — insert — ambiguity — donation requires a non-empty `recipient_name`; scrap `reason` accepted but not recorded — implementation/routes/surplus.py:166,179
- §3.9 — insert — ambiguity — sale price exactly equal to the floor is accepted — implementation/routes/surplus.py:142-144
- §3.10 — insert — ambiguity — unrecognized `basis` → `ERR_INVALID_REQUEST`; logical-clock upper bound always applies even when a window is supplied; window bounds not cross-validated — implementation/routes/departments.py:70-86

### Mismatch-revisions (PRD described different behavior → revised to impl)
- §2.5 + §2.10 — revise — mismatch — derived-field recomputation (grant ledger, PO match posture, card utilization) is computed on read and does NOT refresh `updated_at`/`version` of the owning resource (PRD had claimed it does) — implementation/db.py:102-106, implementation/services.py:165-203,216-229,279-289
- §3.1 + §2.8 rung 9 — revise — mismatch — grant close evaluates the encumbrance guard before the state guard (non-ACTIVE + encumbered → `ERR_GRANT_HAS_OPEN_ENCUMBRANCES`, not `ERR_GRANT_STATE_INVALID`) — implementation/routes/grants.py:101-106
- §3.2 — revise — mismatch — contract-termination cascade flags every non-`CANCELLED` PO including `FULLY_RECEIVED` (PRD had limited it to `ISSUED`/`PARTIALLY_RECEIVED`) — implementation/services.py:430-459
- §3.5 — revise — mismatch — PO issuance has no vendor-designation gate; vendor-less requisitions issue orders with `vendor_id` null (PRD had `ERR_SOURCING_REQUIRED` at issuance) — implementation/routes/requisitions.py:395-430 (esp. patch-site note 407-410)
- §3.8 — revise — mismatch — on reconcile/dispute the transaction-state guard fires before the closed-card guard, so `ERR_CARD_CLOSED` surfaces only for otherwise-actionable transactions (PRD had claimed every reconcile/dispute on a closed card → `ERR_CARD_CLOSED`) — implementation/routes/pcard_transactions.py:129-132,176-179

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1778_university_procurement_p_card_program/workspace/PRD_COMPLETED.md`
