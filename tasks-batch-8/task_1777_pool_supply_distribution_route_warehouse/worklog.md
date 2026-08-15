# Worklog — task_1777_pool_supply_distribution_route_warehouse

## Step 1: Create Task Directory — 2026-08-14T15:31:06.349Z

Pre-assigned directory `tasks/task_1777_pool_supply_distribution_route_warehouse/` with `workspace/` subdirectory already exists (created by pipeline dispatcher). Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched. User directive: difficulty beyond expert level ("Generate task hard than expert level!").

## Step 3: Copy Shared Files — 2026-08-14T15:31:39.412Z

Copied `./INSTRUCTION.md` → `tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/INSTRUCTION.md` (1424 bytes). Done early, concurrent with Step 2 subagent, since Step 3 has no dependency on scaffold output.

## Step 2: Generate Scaffold — 2026-08-14T16:05:35.151Z

All three artifacts are complete, lint-clean, and internally consistent. Summary of what was generated:

## Generated artifacts

All under `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/`:

- **`SCAFFOLD.yaml`** (1407 lines) — §1.0–§1.7: 12 entities, 7 state machines, 3 OCC concurrency rules, 7 calculation rules, 17 ordered validations, 61 endpoints, 51 error codes, 5 roles
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (1135 lines) — 9 rule_ids × 2 instances = 18 difficulty instances, all with structured `setup_api_calls` chains and pre-computed literal asserts
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (1344 lines) — 38 corner instances across 8 sections (32 active recipes + 6 `excluded_because` stubs referencing §1.8 instances)

## Design highlights (per the HARDER-than-expert directive)

- **Archetype**: quota/allocation with compliance/audit secondary; flat topology, parallel state dimensions on SalesOrder (fulfillment × payment), self-referential BackorderRequest chain
- **Rule 1**: freight order-level-vs-per-line trap (SalesOrder domain) vs provisional/final warranty labor credit (WarrantyClaim domain) — different entity domains
- **Rule 2**: mode (a) tier×seasonal×qty non-linear pricing (PREMIER+early-buy: 10000→7200) and mode (b) pinned per-line-round-then-sum (1051c×0.9×0.95×2 = 1797, one cent off the 1798 trap)
- **Rule 3**: SalesOrder parallel dims with guarded join (complete requires PAID) + WarrantyClaim UNDER_REVIEW↔MORE_INFO cycle with 3-cycle exhaustion guard
- **Rule 4**: depth-3 cascade (confirm → line shortage → backorder → branch FROZEN) and depth-2 close-season cascade (branch → program → commitment FULFILLED/DEFAULTED)
- **Rule 5**: state×business_constraint (cancelled order on frozen branch → ERR_ORDER_NOT_DRAFT) and business_temporal×business_fiscal (window closed beats pool exhausted)
- **Rule 6**: tier `>=` boundary at exactly 2,000,000c vs zero-quantity `ERR_LOT_EMPTY` edge
- **Rule 7**: SalesOrder→Branch posture gate and WarrantyClaim→ServiceCenter suspension gate
- **Rule 8**: inclusive-end datetime commitment window vs day-granularity MM-DD peak-season window
- **Rule 9**: lot `qty_available` conservation across confirm/cancel and program pool conservation across supersede (150, not 250)
- **OCC**: three true-race rules with pinned evaluation precedence (state → OCC → business) so stale-version rejections are deterministic and sequentially reproducible

## Verification

`scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional audits passed: all 51 error codes referenced; all endpoint roles resolve to §1.7; instance names unique across both design files; all 6 corner stubs reference existing §1.8 instances; no forbidden concurrency vocabulary; numeric asserts pre-computed as literals (freight 11800, warranty 30000/67500, pricing 21600/1797, RMA credit 27200, tier boundary 2000000).

## Step 4: Generate PRD — 2026-08-14T16:17:09.275Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/PRD.md`. The difficulty/corner design files were not touched.

**Document design** (domain-derived, not template-copied):
- §1: 2-paragraph introduction from the seasonal-business angle; `/pool-supply` mount declared here.
- §2: 11 subsections — roles/auth with per-role identity prose, verbatim §2.2 block, pagination, common resource properties (with the OrderLine no-`updated_at`/no-`version` exception called out), integer-cents/round-half-up precision with the two pinned rounding disciplines, the logical clock (startup default `2026-08-01T00:00:00Z`), branch posture derivation with inclusive boundaries and freeze precedence, OCC (all three rules with endpoint + `expected_*_version` + exact 412 error + pinned evaluation precedence), the validation cascade with per-endpoint business-check ordering, hazmat governance, and the tier ledger/ratchet.
- §3: 9 subsections organized by business timeline (setup → accounts → seasonal programs → order confirm → pricing/freight → fulfillment → backorder waterfall → warranty → returns/closeout). All formulas translated to precise prose (per-line round-before-sum, order-level freight threshold with the per-line trap variant named, waterfall ranking with UUID ban, FEFO with NULLS-LAST expiry ordering, provisional-vs-final warranty credit with clawback, frozen historical price for RMA credit).
- §4: 61-row endpoint table, 4 columns only. §5: 51-row error table, 2 columns only. No audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body/input (incl. outputs like current_utc): 67 required, 67 present, 0 missing
- endpoints[].path_params: 1 ({id}), present
Status: PASS

Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed (global cascade in §2.9; per-endpoint pinned orders for confirm, commitment create, claim create)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (expected_branch_version/ERR_STALE_BRANCH_VERSION, expected_stock_lot_version/ERR_STALE_LOT_VERSION, expected_program_version/ERR_STALE_PROGRAM_VERSION — each with write endpoint, field, error id, HTTP 412)
- state_machines[].transitions: 21 checked, 21 fully expressed (all preconditions paired with error ids, all side effects stated, incl. ALLOCATED→OPEN rollback and FULFILLED→COMMITTED compensation)
- calculations[]: 7 checked, 7 fully expressed in precise prose, constants embedded ($500 free-freight min, 2,500/1,800/7,500-cent freight parts, $20k/$50k tier thresholds, 2h flat / 6h cap, 15% restock)
- validations[] conditions: 17 matchable to error ids in §2/§3 prose; all 51 error ids appear in §2/§3 (verified none live only in §5)
- endpoints[].side_effects / applies_to: all expressed (replenish sweep, close-season cascade, commitment supersede + program version +1, RMA restock rule, ownership applies_to enumeration)
- entities[].fields[] structured content: defaults (90-minute cutoff, PRO tier, NONE hazmat, floor 0, freeze 100, willcall true, credit_hold false), immutability (qty_original, hazmat_storage_class), and common_fields:false exception all reconstructible from prose
- sibling-branch symmetry: parallel branches (settle FULFILLED vs DEFAULTED, WILL_CALL vs ROUTE_DELIVERY freight, DEFECTIVE/WRONG_ITEM vs OVERSTOCK vs EXPIRED fees) rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 457
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-identical to the canonical `section-2.2-response-structure.md` block. No fuzzy/approximating words and no pseudocode operators (`==`, `>=`, `+=`, …) appear anywhere in the document.

## Step 5: Generate Unit Tests — 2026-08-14T16:56:53.517Z

All checks pass. Generation is complete.

## Report

**Outputs** (under `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/`):

- `test_helpers/` — 9 modules: `types.py` (12 entity TypedDicts; `OrderLine` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (one method per PRD §4 endpoint, all 48), `api_errors.py` (full 51-error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity + three-bucket lot-ledger invariant), `factories.py`, `constants.py` (tier thresholds, freight constants, warranty hours, restock fee, default clock), `test_users.py` (5 roles + `make_account_headers` for the entity-backed Account role), `fixtures.py` (composite setups: `setup_branch_account_product_lot`, `create_confirmed_order`, `complete_order_fully`, `seed_account_tier`, `make_open_program_with_commitment`, `confirm_short_order`, `make_claim_under_review`, fresh-version OCC helpers), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 10 test files, **69 test functions**.

**Coverage audit (passed)**: all 18 §1.8 difficulty instances have ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`; all 32 non-stub §1.9 corner instances have ≥1 test tagged `Design: Corner/<section>/<name>`; the 6 `excluded_because:` stubs were not translated and all their `difficulty_instance` cross-references resolve. No orphan/dual/missing tags; no skip/xfail markers.

**Citation audit (passed)**: every docstring's `PRD §x.y: "..."` quote was verified verbatim-greppable against `workspace/PRD.md` (whitespace-normalized). All modules compile and import cleanly against the installed `prd_bench_local_runner` framework.

**Four PRD-first adjudications where design recipes conflicted with the PRD** (PRD won; tags kept on the source instance):
1. `occ_stale_lot_version_on_manual_allocate` — recipe math assumed partial line allocation at confirm; PRD §3.4 pins all-or-nothing ("A line no single lot can cover goes short: `allocated_qty` stays zero"). Rebuilt so the lot is genuinely empty with BO2 OPEN(2) and the stale version still fires before `ERR_LOT_EMPTY` per §2.8 precedence.
2. `confirm_short_backorder_freezes_branch` — recipe expected allocated 3 / backordered 10; PRD all-or-nothing gives 0/13 (still ≥ threshold 10 → FROZEN). Asserted PRD values.
3. `order_parallel_fulfillment_x_payment` — the recipe's invoice-after-mark-loaded step violates PRD §3.6 ("invoicing … requires fulfillment `CONFIRMED`"). Tests pin the PRD-consistent semantics: `ERR_ORDER_UNPAID` at the guarded join, invoice-after-load rejected with `ERR_ORDER_NOT_CONFIRMED`, and the viable join path (invoice → pay → mark-loaded → complete).
4. `branch_create_defaults_applied` — dropped the `version == 1` literal (PRD §2.4 says version "starts at its initial value" without pinning it; fails the two-reader test); kept the covered defaults (90 / OPEN / NORMAL / pool 0) and bare-UUID assertions.

## Step 6: Generate Implementation — 2026-08-14T16:56:53.517Z

Implementation complete and verified. Summary:

## What was built

A complete Python + Flask implementation of the Pool Supply Distribution API in `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/implementation/` (~2,275 lines):

- **`start.sh`** — foreground launcher with the guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — blueprint registration + error handlers (unmatched routes/methods map to the catalog's `ERR_RESOURCE_NOT_FOUND` 404 envelope)
- **`db.py`** — in-memory store, starts empty on every boot (no seeding); monotonic `_seq` counter backs all `created_at ASC` orderings (FEFO tie-break, waterfall rank, list sort) so same-millisecond creations can't tie
- **`errors.py`** — full 46-code error catalog with exact IDs and HTTP statuses
- **`response.py`** — exact envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields (`limit/offset/total_count/has_more`) in `meta` for lists only
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth (priority 1), role gating (2), Account ownership (`ERR_NOT_RESOURCE_OWNER` / claim-specific `ERR_NOT_CLAIM_OWNER`)
- **`util.py`** — logical clock defaulting to exactly `2026-08-01T00:00:00Z` (settable in either direction — the corner design moves it backward), Decimal `ROUND_HALF_UP`
- **`services.py`** — all six calculations: per-line round-then-sum pricing (extended rounded before summing; unit derived from the rounded extended), order-level freight with hazmat surcharge and capped shortfall, tier ratchet (>= boundaries), priority-snapshot backorder waterfall, branch posture (FROZEN over CONSTRAINED over NORMAL, computed on read), warranty provisional/final credit (round-before-cap), RMA credit against frozen historical unit price
- **`routes/`** — all 61 endpoints across 11 blueprints

## Key spec decisions

- **Confirm gauntlet order** follows PRD §3.4 exactly: DRAFT/branch-OPEN state → OCC `expected_branch_version` (412) → hazmat storage → hazmat license (strict `>`) → route-date window (day-granularity peak-end compare) → will-call auth → FROZEN posture → commitment exhaustion → fiscal (402)
- **Partial FEFO allocation at confirm**: full-cover lots preferred (earliest expiry, then creation order); if none covers, the best lot with any stock grants what it has and the residual becomes an OPEN backorder — matching the numeric asserts in the difficulty design (e.g., lot 3 / qty 13 → `allocated_qty == 3, backordered_qty == 10`)
- **OCC precedence**: state before version before business on all three OCC endpoints (stale lot version reported even when the lot is empty)
- **Cancel compensation**: reservations released, OPEN backorders cancelled, ALLOCATED backorders roll back via the reassignment path, commitment consumption reverted (FULFILLED → COMMITTED), ytd decremented for invoiced orders with tier ratchet holding

## Verification

Four smoke suites (~90 assertions) run against fresh `bash start.sh` boots — all passing: every corner/difficulty design scenario (FEFO, freight variants, rounding-order trap, waterfall priority, OCC triple, window boundaries, info-cycle exhaustion, expired-chemical guards at create/approve/receive, close-season cascade, cancel unfreeze, tier boundaries at exactly 2000000/5000000), plus envelope/pagination/RBAC checks and a reboot test confirming the store starts empty per the per-test-server isolation contract.

## Orchestrator note (pre-Step-7 signal)

Step 5's tests assert all-or-nothing line allocation at confirm (PRD §3.4: "A line no single lot can cover goes short: `allocated_qty` stays zero, `backordered_qty` equals the full `qty`" — e.g. lot 3 / qty 13 → 0/13), while Step 6's implementation reports partial FEFO allocation for the same scenario (3/10). This is a known PRD-vs-design-index conflict to be adjudicated in Step 7 with PRD as the contract. Also noted: Step 6 reports a "46-code error catalog" while SCAFFOLD/PRD declare 51 error codes — Step 7 will reconcile against PRD §5.

## Step 7: Run Tests and Iterate — 2026-08-14T17:05:00.000Z

All 8 rounds of the post-fix sweep pass 69/69 with zero failures and zero errors. The sweep is clean — exiting with the summary.

**Summary**

- **Iterations run:** 2 (baseline sweep → fixes → confirmation sweep; confirmation sweep: all 8 rounds × 69 tests passed, 552/552 executions).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none. The shared fixtures/factories/header builders were audited end-to-end (fixtures.py, factories.py, test_users.py, assertions.py) and construct PRD-consistent preconditions throughout.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/test_suite/test_05_backorders_posture.py` — `test_backorder_waterfall_priority_order_premier_first`: replaced the second `confirm_short_order()` call with direct `make_order` + `confirm_order`. The asserted rule (waterfall priority ranking, PRD §3.7 "Candidates are ranked by `priority_rank` ascending, ties broken by `created_at` ascending") is verbatim-covered and uniquely derivable, so the test stays; the bug was in its setup path — the `confirm_short_order` fixture internally asserts exactly one OPEN backorder per (branch, product), but this test legitimately creates two (PRO qty 3, then PREMIER qty 2), so the second fixture call failed with "expected exactly one OPEN backorder, got 2" in all 8 baseline rounds. The replacement mirrors the sibling test `test_waterfall_sweep_exact_grant_leaves_second_untouched`, which already uses the correct pattern.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/implementation/services.py` — `fefo_allocate()`: removed the partial-grant fallback (preference 2). PRD §3.4 pins all-or-nothing confirm-time allocation verbatim ("A line no single lot can cover goes short: `allocated_qty` stays zero, `backordered_qty` equals the full `qty`"), so the function now returns `(None, 0)` when no single lot covers the full line quantity, and the caller leaves `allocated_qty` zero and births a backorder for the full `qty`. This was the known pre-flagged generation conflict; PRD won over the difficulty-recipe numbers (lot 3 / qty 13 → 0/13, not 3/10). The §3.7 waterfall sweep correctly retains partial grants ("granting each the smaller of its `qty_open` and the lot's remaining `qty_available`") — that path was left untouched.

- **Error catalog reconciliation:** verified PRD and implementation both define the identical set of 51 `ERR_*` ids (`diff` of sorted unique sets: empty). The worklog's "46-code catalog" note was stale; no change needed.

## Step 8: Finalize PRD — 2026-08-14T17:10:00.000Z

## Summary

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/PRD_FINALIZED.md` — produced as a verbatim copy of `PRD.md` (the minimal patch is the empty patch).

**Line counts / %-delta:** PRD.md 328 lines; PRD_FINALIZED.md 328 lines; delta 0 lines, 0.0%. Files are byte-identical (`diff` clean).

### Why zero edits — per step_7_diff item

- **§3.7 test fix (`test_05_backorders_posture.py::test_backorder_waterfall_priority_order_premier_first`)** — pure fixture bug, no PRD silence. The `confirm_short_order` helper (`test_helpers/fixtures.py:301-311`) routes through `get_single_backorder`, which asserts exactly one OPEN backorder per (branch, product); the test legitimately births two (PRO qty 3, then PREMIER qty 2). The asserted ranking rule is pinned verbatim in PRD §3.7 line 180 ("Candidates are ranked by `priority_rank` ascending, ties broken by `created_at` ascending; the UUID `id` must never be used as a ranking key"), and coexistence of multiple OPEN backorders per (branch, product) is already determined by §3.7 line 178 (one backorder birthed per short line, no uniqueness constraint) plus line 180's plural candidate set. Nothing to pin.

- **§3.4 implementation fix (`services.py::fefo_allocate`)** — impl was repaired *to* the PRD, not the reverse. PRD §3.4 line 156 already pins all-or-nothing twice verbatim: "among the branch's lots of the line's product holding enough unreserved units to cover the **full line quantity**" and "A line no single lot can cover goes short: `allocated_qty` stays zero, `backordered_qty` equals the full `qty`". The conflicting "lot 3 / qty 13 → 3/10" numbers never appeared in the PRD (grep for partial/numeric allocation examples: only the two verbatim pins at lines 156 and 180 exist). §3.7 line 180 separately pins partial grants for the waterfall ("granting each the smaller of its `qty_open` and the lot's remaining `qty_available`"), matching the untouched `sweep_backorders_for_lot`. Keep prose verbatim.

- **Error catalog** — independently re-verified: 51 `ERR_*` ids in `implementation/errors.py`, 51 in PRD.md, `diff` of sorted unique sets empty. No change.

### Pre-edit search log

No edits were committed, so no wording needed validation. The mandatory enumeration was still performed for each candidate edit subject:

1. **Subject: confirm-time FEFO all-or-nothing vs partial grant.** Paths enumerated and read: `implementation/services.py:69-89` (`fefo_allocate` — returns `(None, 0)` when no single lot covers full qty), `implementation/routes/orders.py:233-249` (confirm caller — short line leaves `allocated_lot_id=None`, `allocated_qty=0`, births backorder for full qty), `services.py:181-192` (`create_backorder` — `qty_original`/`qty_open` = full shortage). All conform to PRD §3.4 line 156 verbatim → no edit; wording adjustment: none needed.

2. **Subject: waterfall grant size and ranking.** Paths enumerated: `services.py:211-232` (`sweep_backorders_for_lot` — `grant = min(qty_open, available)`, ranking key `(priority_rank, _seq)`), `routes/backorders.py:36-69` (manual allocate — same `min` grant, guards per §2.8/§3.7), `routes/stock_lots.py:76` (replenish trigger), `routes/orders.py:318-344` (cancel rollback re-sweeps only OPEN backorders). All conform to PRD §3.7 lines 178-184 verbatim → no edit; wording adjustment: none needed.

3. **Subject: error catalog.** Enumerated `implementation/errors.py` vs all `ERR_*` tokens in PRD.md; identical sets → no edit.

A fresh implementer reading `PRD_FINALIZED.md` alone is already fully determined at every site Step 7 touched: the implementation now exhibits exactly what the PRD's existing prose uniquely pins.

## Step 9: Complete PRD — 2026-08-14T17:16:00.000Z

The diff confirms exactly 26 edited lines (26 `<` + 26 `>` = 52), all in-paragraph revisions — no sections added. The work is complete.

**Summary**

- **Source vs. output**: `PRD_FINALIZED.md` — 328 lines, 49,866 chars → `PRD_COMPLETED.md` — 328 lines, 53,969 chars (+4,103 chars; 26 lines edited in place, 0 lines added/removed).
- **Counts**: 26 ambiguity-pins, 0 mismatch-revisions (implementation matched PRD prose everywhere a behavior was pinned; every edit closed silence).

Changes, one bullet each:

- §2.2 Standard Success Response — insert — ambiguity — pinned that `api_request_timestamp` (and by extension `created_at`/`updated_at` bookkeeping) is stamped from the host wall clock, not the logical clock — implementation/util.py:18-22.
- §2.2 Standard Error Response — insert — ambiguity — pinned that unknown paths and wrong methods on known paths return `ERR_RESOURCE_NOT_FOUND` (404) — implementation/app.py:28-34.
- §2.3 Pagination — insert — ambiguity — pinned `ERR_INVALID_REQUEST` for `limit` < 1 or non-integer and for `offset` < 0 or non-integer, and creation-order tie-break when `created_at` values tie within one millisecond — implementation/routes/helpers.py:20-43, implementation/db.py:24-31.
- §2.4 Common Resource Properties — insert — ambiguity — pinned `version` starts at 1 — implementation/services.py:31-37.
- §2.6 Logical Clock — insert — ambiguity — pinned that `set_current_utc` accepts any instant (forward or backward) — implementation/util.py:60-62.
- §2.7 Branch Stock Posture — insert — ambiguity — pinned posture as a live derived value, and that only `OPEN` backorders count toward the freeze load (ALLOCATED excluded) — implementation/services.py:96-117, routes/branches.py:19-23.
- §2.8 OCC — insert — ambiguity — pinned that a missing/null/non-integer expected-version field is `ERR_INVALID_REQUEST` (400) on all three OCC endpoints — implementation/routes/orders.py:178-183, routes/backorders.py:47-51, routes/programs.py:107-111.
- §2.8 OCC (commitment bullet) — insert — ambiguity — pinned that the program-version check runs after the open-state precondition, before window/pool checks — implementation/routes/programs.py:103-113.
- §2.11 Volume Ledger — insert — ambiguity — pinned the operational running-integer mechanism (increment at invoicing, decrement floored at zero on cancel of an invoiced order) that realizes the defined sum — implementation/routes/orders.py:384-389, 362-367.
- §3.1 Branch creation — insert — ambiguity — pinned `posture` and `seasonal_pool_units` as computed-on-read derived values — implementation/routes/branches.py:19-23.
- §3.1 Stock lots — insert — ambiguity — pinned lot `expiry_date` reciprocity errors (missing for expiry-tracked product or present for non-tracked product → `ERR_INVALID_REQUEST`), `qty_available` as derived, and `add_qty` minimum of 1 — implementation/routes/stock_lots.py:31-39, 73.
- §3.2 Accounts — insert — ambiguity — pinned that client-supplied `tier`/`ytd_volume_cents` at creation are ignored, license is nullable via PATCH, and a no-change PATCH does not bump `version`/`updated_at` — implementation/routes/accounts.py:27-28, 73-77, 85-86.
- §3.3 Programs — insert — ambiguity — pinned window validity is checked only at open time (order window before ship window), and commitment creation on a non-`OPEN` program draws `ERR_PROGRAM_NOT_OPEN` — implementation/routes/programs.py:66-71, 104-105.
- §3.4 Order draft — insert — ambiguity — pinned that `lines` may be an empty array, channel-required field omission is `ERR_INVALID_REQUEST`, a supplied `commitment_id` must resolve (404) but is otherwise validated only at confirm, and draft orders carry `tier_at_confirm` null with zeroed money fields — implementation/routes/orders.py:52-66, 70-71, 86-99.
- §3.4 Confirm side effects — insert — ambiguity — pinned that each FEFO lot reservation also increments the touched lot's `version` — implementation/routes/orders.py:242-243.
- §3.6 Cancellation — insert — ambiguity — pinned that only orders already `INVOICED`/`PAID` decrement `ytd_volume_cents` (floored at zero); cancelling an `UNINVOICED` order touches no volume — implementation/routes/orders.py:363-366.
- §3.7 Manual allocation — insert — ambiguity — pinned the branch/product lot-match check as `ERR_INVALID_REQUEST` evaluated after the OCC version check and before the empty-lot check — implementation/routes/backorders.py:54-55.
- §3.8 Center selector — insert — ambiguity — pinned that because accounts carry no region attribute, the region criterion never discriminates; the selector effectively sorts by `labor_rate_cents` then `created_at` — implementation/routes/claims.py:62-64.
- §3.8 Claim creation — insert — ambiguity — pinned new claims carry `final_credit_cents`/`actual_labor_hours` null and `info_cycles` 0 — implementation/routes/claims.py:75-77.
- §3.8 Supply-info — insert — ambiguity — pinned that a successful supply moves the claim back to `UNDER_REVIEW` — implementation/routes/claims.py:136.
- §3.9 RMA request — insert — ambiguity — pinned that all three expiry guards (request, approve, receive) fire only when the lot carries an `expiry_date`, and that fresh requests store `restocking_fee_pct`/`credit_cents` as null — implementation/routes/rmas.py:48-53, 62-63.
- §3.9 RMA approval — insert — ambiguity — pinned check order (state → order-`COMPLETED` → expiry re-check → credit) and that `restocking_fee_pct` is stored as the applied fraction (0.15, else 0) — implementation/routes/rmas.py:91-107.
- §3.9 RMA receive — insert — ambiguity — pinned that a receipt restocking nothing leaves the lot's `version` unchanged — implementation/routes/rmas.py:142-144.
- §3.9 Closeout — insert — ambiguity — pinned that closing a non-`OPEN` branch draws `ERR_INVALID_STATE` — implementation/routes/branches.py:57-58.

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_1777_pool_supply_distribution_route_warehouse/workspace/PRD_COMPLETED.md`
