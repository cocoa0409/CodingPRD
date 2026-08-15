# Worklog — task_1612_tour_merchandise_venue_split_management

## Step 1: Create Task Directory — 2026-08-14T01:36:00.000Z

Task directory `tasks/task_1612_tour_merchandise_venue_split_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T02:35:00.000Z

All three scaffold artifacts are generated, lint-clean, and cross-verified.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 (no design keys): 11 entities, 7 state machines, 2 OCC concurrency rules, 9 calculations, 16 priority-ordered validations, 54 endpoints, 47 error codes, 4 roles. No sibling task was read; design derived purely from the scenario + skill spec.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single `scaffold_difficulty_design:` key; 9 rules × 2 instances = 18, every instance with structured `setup_api_calls`/`trigger`/`assert` and code-verified literal values (e.g., provisional commission 119550 vs final 120000; tier straddle 110000; largest-remainder tie split 26/25/25/25; royalty 50000 exactly at the 500000 threshold).
- **SCAFFOLD_CORNER_DESIGN.yaml** — single `scaffold_corner_design:` key; 52 instances across all nine claim-extraction-guide sections (44 active recipes + 8 `excluded_because` stubs citing §1.8 instances).

## Key design decisions

- **Profile**: ledger_reconciliation primary + quota_allocation secondary; layers = dual-variant calc, cascading side effects, OCC, rate/threshold triggers; **flat** topology (`/merch/<resource>` peers, FK in body/query); **segregation_of_duties** role model (session verifier ≠ counter, settlement finalizer ≠ reconciler, shipment receiver ≠ dispatcher).
- **Dual variants on different domains**: venue commission provisional (drawer cash + card) vs final (register) on Settlement; online royalty creation-snapshot vs fulfill-recompute on OnlineOrder.
- **Non-linear machines on different entities**: Settlement RECONCILED↔DISPUTED cycle with audit-void recompute; SellerSession COUNTED_OUT→OPEN recount loop.
- **Cascades**: close-out → Allocation → Show → auto-close Tour (depth 3); finalize → Show → session lockdown (depth 2).
- **Design fix found during authoring**: rebase-royalty originally allowed only in PROVISIONAL/DISPUTED while finalize requires RECONCILED — a deadlock once a config change lands after reconciliation. Resolved by permitting rebase in RECONCILED with royalty-figure recompute (recorded in SCAFFOLD state machine).

## Verification

- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (596 calls scanned; two initial FK-reachability findings fixed by adding `settlement_id?` and `product_id?` list filters.)
- Mechanical audits: 70 unique instance names across both files, zero forbidden concurrency vocabulary, all error codes both declared and referenced, all `grounds:` refs resolve, all stub citations valid, all pinned arithmetic recomputed and confirmed, enum-value closure holds for all 7 machines.

## Step 3: Copy Shared Files — 2026-08-14T02:36:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1612_tour_merchandise_venue_split_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T02:52:00.000Z

The PRD generation task is complete and verified. The existing task list covers prior scaffold work (all completed); this deliverable is a single-file generation now finished, so no new task tracking is warranted.

## Report

**Generated**: `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/workspace/PRD.md` from `SCAFFOLD.yaml` (the two `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened).

**Document shape**: 2-paragraph introduction (business-context angle); §2 with 10 domain-derived subsections (RBAC with per-role identity prose, verbatim §2.2 envelope, pagination, resource identity/versioning, cents+basis-points rounding discipline, logical clock with 2026-08-01T00:00:00Z default, 16-step validation precedence ladder, segregation-of-duties control pairs, OCC, pinned royalty snapshots); §3 with 8 lifecycle-grouped subsections (tour/catalog, shows/pricing, allocation/routing, show-day selling/cash, settlement lifecycle, close-out, online store, corrections/audit); §4 endpoint table with exactly 4 columns and 54 rows; §5 error catalogue with exactly 2 columns and 47 rows. No audit footer after §5.

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body/inputs: 58 required, 58 present, 0 missing
- endpoints[].query_params (filters, limit/offset): all present, 0 missing
- errors[] ids: 47 required, 47 present in §2/§3 prose, 0 missing
- roles + all 36 enum/state values: present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ladder: 16 ordered steps expressed in §2.7 with error ids and statuses, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (royalty-config → expected_tour_version; show-product reprice → expected_show_product_version; both → ERR_STALE_VERSION/412, stale-view framing only), 0 missing
- state_machines[].transitions: 23 checked (incl. system cascades and 3 rebase self-loops), 23 fully expressed with preconditions + error ids + side effects, 0 missing
- calculations[]: 9 checked (size-curve largest-remainder with pinned S<M<L<XL<OS tie order, commission FLAT/TIERED per-bracket round-then-sum, tiered marginal royalty with exact boundary, per-product-max licensing, session cash reconciliation, online royalty provisional/final divergence, warehouse stock ledger, close-out conservation invariant, tour royalty rollup), 9 fully expressed in reconstructible prose, 0 missing
- validations[] conditions: all matchable to their error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to scopes: all expressed (finalize cascade, close-out cascades, dispatch/receive/cancel compensation, void ripples incl. variance recompute while COUNTED_OUT, ERR_CROSS_TOUR_REFERENCE across all 5 endpoints), 0 missing
- entities[].fields[] structured content: defaults (size curve 1/2/2/1, tolerance 1000 cents, sized=true, empty stock map, null finals), constraints, immutability, and pinned-price semantics reconstructible, 0 missing
- sibling-branch symmetry: FLAT/TIERED, APPROVE/REJECT, WAREHOUSE/SHOW origins, sized/non-sized/BUNDLE fulfill, Seller/Accountant void paths, rebase across 3 states — all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 458
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the canonical block byte-for-byte (confirmed via substring test against `section-2.2-response-structure.md`); no pseudocode operators or fuzzy quantifiers anywhere; all endpoints named in §3 via state-transition framing or role+verb; the logical-clock endpoint path appears only in §2.6 (allowed outside §3).

## Step 5: Generate Unit Tests — 2026-08-14T03:30:00.000Z

Test generation for task_1612 is complete. All audits pass.

## What was generated

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/test_helpers/`:
- `types.py` — 11 entity TypedDicts + 13 status/domain enums (all entities carry the full common field set)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 41 endpoint methods incl. the `_clock/set_current_utc` test-driving endpoint
- `api_errors.py` — all 40 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_allocation_conservation` / `assert_settlement_final_figures` invariant checkers
- `factories.py` — per-entity payload factories (optional fields omitted unless given, so server defaults are exercised)
- `constants.py` — royalty config defaults, tolerance 1000, default curve {S:1,M:2,L:2,XL:1}, initial clock 2026-08-01T00:00:00Z, 48h lead time
- `test_users.py` — opaque-role constants (tm-1/tm-2/acct-1/acct-2/venue-1) + `make_seller_headers(user_id)` for the entity-backed Seller role
- `fixtures.py` — Tier-1 step helpers plus composite `setup_selling_show` (tour→show→product→price→allocations→sellers→open), `staff_session` (session→sales→count-out→verify), and `reach_settlement(world, PROVISIONAL|RECONCILED|FINALIZED)`

**`test_suite/`** — `conftest.py` + 8 test files, **79 tests**: 36 difficulty (18/18 instances × 2) + 43 corner (43/44 non-stub).

## Audits run
- **Completeness**: every difficulty instance has exactly ≥2 `Design: Difficulty/...` tags; every non-stub corner instance ≥1 `Design: Corner/...` tag; all 8 corner `excluded_because` stubs left untranslated with cross-references verified; no unknown/dangling tags; no skip/xfail markers.
- **Verbatim citation**: all 135 `PRD §...` quoted spans verified literal-present in PRD.md (whitespace-normalized).
- **Collection**: `pytest --collect-only` yields 79 tests cleanly with the runner's PYTHONPATH.

## Skipped instance (gap left as gap)
`Corner/entities/product_create_rejects_computed_field_input` — asserts a client-supplied `warehouse_stock_by_size` is rejected with `ERR_VALIDATION`. PRD §3.1 only says the field "is never written directly; it is a derived figure" — a faithful PRD-only implementer could silently ignore the input, so the asserted outcome fails the unique-derivability condition.

## Two-reader relaxations applied
- Initial `version` value is never pinned in the PRD, so the tour-defaults test asserts only a positive int (all version assertions elsewhere are relative `v+1`, per "increments by exactly one").
- Allocation generate response row order is not pinned, so the size-curve tie test indexes rows by `size` rather than position.
- `dispatched_at` asserted as an ISO-8601 timestamp with the `2026-08-01T00:00:00` prefix (fractional-digit formatting isn't pinned for that field).
- Priority-pair tests are kept (not skipped under the validation-priority silence pattern) because PRD §2.7 explicitly enumerates the check order ("the earliest failing check wins" + numbered list).

## Step 6: Generate Implementation — 2026-08-14T03:30:00.000Z

Implementation complete and verified. Summary:

## Deliverable

Full Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/workspace/implementation/`:

- **`start.sh`** — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Fresh boot answers HTTP in ~600ms.
- **`app.py`** — Flask entry, error handlers, 12 blueprints.
- **`db.py`** — in-memory store, empty on every boot (no seeding), logical clock defaulting to `2026-08-01T00:00:00Z`.
- **`clock.py` / `response.py` / `errors.py` / `middleware.py`** — logical clock with 3-fractional-digit ISO stamps; the exact `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` list pagination (10/0 defaults, 1–100 clamp); full error catalog from the scaffold; `X-User-ID`/`X-User-Role` auth with the Seller-must-be-an-existing-Seller rule.
- **`routes/`** — all 33 endpoints: tours (incl. OCC royalty-config PATCH, activate/close), shows (open/begin-reconciliation/cancel/close-out), products (bundle validation), show-products (OCC reprice), allocations (largest-remainder size-curve split, returns `response_type: "array"` with 201), sellers, seller-sessions (count-out/verify with SoD + variance-override gate + recount loop), sale-records (pinned pricing, Seller/Accountant void paths), online-orders (provisional vs final royalty), settlements (reconcile/dispute/resolve/finalize/rebase-royalty with pinned snapshot + SoD + stale-config gate + cascade to show SETTLED and sessions LOCKED), shipments (48h lead time off the logical clock, WAREHOUSE/SHOW origins, SoD receive, cancel-with-restore), and `_clock/set_current_utc`.
- **`services/`** — derived-state engine: warehouse stock ledger (shipments by status + fulfilled orders + close-out returns), tiered/flat commission with per-segment `Decimal` ROUND_HALF_UP, marginal artist royalty, per-product licensing max, session expected-cash/variance, tour royalty rollup.

## Verification

Two smoke suites run against a live boot passed clean:
- **SMOKE OK** — 100+ assertions across the full cycle: auth failures, tour OCC (412), venue-date conflicts, commission-config shape errors, size-curve split 60→10/20/20/10, session uniqueness/double-booking, sale ownership (403), oversell (409), variance gate with manager override, provisional figures (drawer cash + card), reconcile math, dispute/resolve, stale-royalty finalize block + rebase remedy, finalize cascade, close-out conservation + shrinkage + warehouse restock + credit, shipment SoD/lead-time/receive-upsert, online fulfill stock decrement, royalty rollup, pagination meta.
- **EDGE OK** — largest-remainder tie-breaking (incl. show-level curve override), tiered marginal commission and royalty above threshold, REJECT recount loop clearing counted/variance, audit void during dispute flowing into resolve recompute, SHOW-origin dispatch decrement + cancel-restore compensation, cross-tour shipment rejection, `ERR_CLOSEOUT_INCOMPLETE`, tour auto-close vs manual close, and `ERR_ALREADY_TERMINAL` on writes to a CLOSED tour.

Validation ordering follows PRD §2.7 (auth → role/ownership → existence → state → OCC → cross-tour → price → temporal → uniqueness → shape → SoD → variance → sufficiency → stale-royalty); I reordered several handlers after a priority audit so FK existence precedes shape checks and OCC precedes body validation on the two version-guarded writes. Two expectation bugs found during testing were in my smoke scripts, not the implementation (curve {M:3,L:1} over 9 units correctly yields M=7/L=2). Ready for the Step 7 test-iteration loop under `prd-bench-local-run --isolation per-test-server`.

## Step 7: Run Tests and Iterate — 2026-08-14T03:50:00.000Z

Exit condition met: all 8 parallel rounds show `passed == total == 79/79`.

---

## Summary

- **Iterations run:** 2 (initial sweep: 78/79 in all 8 rounds with 1 consistent failure; post-fix sweep: 79/79 in all 8 rounds).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/test_suite/test_04_sessions_and_selling.py` — `test_duplicate_session_show_product_and_allocation_rejected`: restructured setup ordering. The test previously used `setup_selling_show` with default `open=True`, then attempted duplicate show-product and allocation-generation creates against an **OPEN** show while asserting `ERR_SHOW_PRODUCT_EXISTS` / `ERR_ALLOCATIONS_EXIST`. PRD §2.7 runs state preconditions (check 4) before uniqueness (check 11) — "the earliest failing check wins" — and PRD §3.2/§3.3 gate both creates on a `SCHEDULED` show, so the PRD-determined response on an OPEN show is `ERR_INVALID_SHOW_STATE` (what the implementation correctly returned). Fix: build the world with `open=False`, assert the two duplicate errors while the show is SCHEDULED, then `open_show(...)` and assert the session duplicate (`ERR_SESSION_EXISTS`, which requires an OPEN show). All three exact `error_id` assertions preserved; only the preconditions changed to match PRD.

- **Fixes applied to `implementation/`:** None — the implementation's check ordering (state gate before uniqueness in `routes/show_products.py::create_show_product` and `routes/allocations.py::generate_allocations`) was already faithful to PRD §2.7.

## Step 8: Finalize PRD — 2026-08-14T04:00:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/workspace/PRD_FINALIZED.md` and is a byte-identical copy of `PRD.md` — **zero edits were warranted**.

## Summary

- **Line counts / %-delta:** PRD.md 314 lines, PRD_FINALIZED.md 314 lines, 0% delta (files identical).
- **Changes:** None.

## Why no edits

The `<step_7_diff>` contains exactly one item: a `test_suite/` fix to `test_04_sessions_and_selling.py::test_duplicate_session_show_product_and_allocation_rejected`, with **no implementation fixes, no test deletions, no test_helpers fixes**. I traced it through the implementation and PRD:

- The old test attempted duplicate show-product and allocation-generation creates against an **OPEN** show while asserting `ERR_SHOW_PRODUCT_EXISTS` / `ERR_ALLOCATIONS_EXIST`. The implementation returned `ERR_INVALID_SHOW_STATE` — which is what the PRD already uniquely determines:
  - **PRD §2.7** (line 90-107) runs state preconditions (check 4) before uniqueness (check 11): "the earliest failing check wins."
  - **PRD §3.2** (line 141): "the row can be created only while the show is `SCHEDULED`" — a show-state precondition mapping to `ERR_INVALID_SHOW_STATE` under §2.7 check 4.
  - **PRD §3.3** (line 145) names it explicitly: "attempting it on a show no longer `SCHEDULED` fails with `ERR_INVALID_SHOW_STATE`."
  - **PRD §3.4** (line 159): sessions require an `OPEN` show, and duplicate show-and-seller → `ERR_SESSION_EXISTS`.
- The implementation matches verbatim: `routes/show_products.py:59-61` (state gate at line 59 precedes the uniqueness scan at lines 67-70), `routes/allocations.py:51-53` (state gate precedes the duplicate scan at lines 61-64), `routes/sessions.py:68-69, 85-87` (OPEN gate, then `ERR_SESSION_EXISTS`).
- Step 7's own diff text confirms: "the implementation's check ordering ... was already faithful to PRD §2.7."

This is the pure-fixture-bug case the method anticipates: the test's preconditions were wrong (duplicate checks must run while SCHEDULED; only the session duplicate belongs on an OPEN show), the PRD pinned the correct behavior all along, and the implementation never diverged. Patching the PRD here would invent specificity the diff does not trace to, violating the hard scope.

## Per-edit pre-edit search log

No edits were committed, so there is no per-edit log. For the single candidate subject considered and rejected:

- **(a) Subject:** check ordering (state preconditions before uniqueness) and the SCHEDULED-state gates for `create_show_product` / `generate_allocations`, plus the OPEN gate for `create_session`.
- **(b) Impl paths enumerated and read:** `implementation/routes/show_products.py` (`create_show_product` lines 40-85, `reprice_show_product` lines 109-134 — same state-gate family), `implementation/routes/allocations.py` (`generate_allocations` lines 37-87), `implementation/routes/sessions.py` (`create_session` lines 47-102, plus `count_out`/`verify_session` which share the show-state errors); cross-checked PRD §2.7, §3.2, §3.3, §3.4 and the §4 endpoint table; checked `test_helpers/fixtures.py:237-276` (`setup_selling_show` `open=` semantics) and grepped the test suite for `ERR_INVALID_SHOW_STATE` usages.
- **(c) Outcome:** every enumerated path's behavior is already uniquely described by existing PRD prose; any insertion would have restated pinned behavior at best and risked narrowing it at worst (e.g., implying the state-before-uniqueness ordering is specific to these two endpoints, when the implementation applies §2.7 globally). Rejected — no wording added.

## Step 9: Complete PRD — 2026-08-14T04:20:00.000Z

PRD_COMPLETED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1612_tour_merchandise_venue_split_management/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 314 lines / 51,268 chars → `PRD_COMPLETED.md` 317 lines / 54,736 chars (char-delta +3,468). 21 edited passages (41 changed diff lines).

**Counts:** 18 ambiguity-pins, 3 mismatch-revisions.

### Mismatch revisions
- §3.1 Bundles — revise — mismatch — a cross-tour bundle component (and a component id matching no product) is rejected with `ERR_BUNDLE_COMPONENT_INVALID`, not the cross-tour error the PRD implied; also pinned that a `REGULAR` product must leave `bundle_components` null — implementation/services/core.py:417-428, routes/products.py:61-63.
- §3.4 Session create — revise — mismatch — double-booking is keyed on sessions attached to non-`CANCELLED` shows (sessions have no `CANCELLED` status), and a same-show conflict reports `ERR_SESSION_EXISTS` while a different-show same-date conflict reports `ERR_SELLER_DOUBLE_BOOKED` — routes/sessions.py:77-89.
- §3.6 Close-out — revise — mismatch — on-hand allocations must appear in lines **at least once** (not "exactly once"); multiple lines per allocation are aggregated per action, and the sufficiency check applies to the per-allocation aggregate, not per line — routes/shows.py:213-248.

### Ambiguity pins
- §2.2 Success format — insert — ambiguity — list rows and create/modify responses carry the same computed fields as single-resource reads — services/serializers.py:7-64.
- §2.2 Error format — insert — ambiguity — unmatched route/method returns the error envelope with `ERR_VALIDATION` at HTTP 404/405; unexpected failures the same at 500 — app.py:17-29.
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1..100, or negative `offset` → `ERR_VALIDATION` (400); `has_more` = `offset + limit < total_count` — middleware.py:142-167, response.py:37.
- §2.4 Versioning — insert — ambiguity — `version` starts at 1 on creation — middleware.py:133.
- §2.6 Logical clock — insert — ambiguity — the logical clock also serves every `created_at`/`updated_at` and every `api_request_timestamp` — middleware.py:132, response.py:18, clock.py:39-40.
- §2.7 item 12 — insert — ambiguity — the `ERR_VALIDATION` catch-all also covers out-of-range basis-point rates and negative cent amounts — middleware.py:72-91.
- §2.9 OCC — insert — ambiguity — the expected-version field is required; missing/non-integer → `ERR_VALIDATION` (400); stale integer → `ERR_STALE_VERSION`, checked before remaining body-shape validation — routes/tours.py:132-145, routes/show_products.py:121-130.
- §3.1 Tour close — insert — ambiguity — closing a non-`ACTIVE` tour → `ERR_INVALID_TOUR_STATE` — routes/tours.py:109-110.
- §3.1 Royalty-config patch — insert — ambiguity — patch accepted on `PLANNING`/`ACTIVE`; on `CLOSED` → `ERR_ALREADY_TERMINAL` — routes/tours.py:127-129.
- §3.2 Show create — insert — ambiguity — request shape, `size_curve`, and commission config are validated before the venue-calendar check — routes/shows.py:63-85.
- §3.2 Show open — insert — ambiguity — the show's `SCHEDULED` check runs before the tour-`ACTIVE` gate, so `ERR_INVALID_SHOW_STATE` wins when both fail — routes/shows.py:130-134.
- §3.3 Allocation generate — insert — ambiguity — cross-tour product → `ERR_CROSS_TOUR_REFERENCE`; `BUNDLE` → `ERR_VALIDATION`; `total_units` non-negative; success is HTTP 201 `response_type` "array" in ascending size order — routes/allocations.py:56-87, services/core.py:146.
- §3.3 Shipment create — insert — ambiguity — every line's product must belong to the shipment's tour (else `ERR_CROSS_TOUR_REFERENCE`); origin-field/line shape validated before the cross-tour check — routes/shipments.py:105-133.
- §3.3 Shipment terminal — insert — ambiguity — a dispatch attempt on a `RECEIVED`/`CANCELLED` shipment also fails with `ERR_ALREADY_TERMINAL` — routes/shipments.py:205-208.
- §3.4 Session create — insert — ambiguity — `cash_float_cents` is validated before the OPEN-show gate — routes/sessions.py:66-69.
- §3.4 Count-out — insert — ambiguity — `counted_cash_cents` must be a non-negative integer — routes/sessions.py:144.
- §3.5 Begin-reconciliation — insert — ambiguity — the response returns the updated show object (settlement reachable via `settlement_id`) — routes/shows.py:173.
- §3.5 Commission — insert — ambiguity — a commission base at or below zero yields zero commission — services/core.py:157-158.
- §3.6 Close-out — insert — ambiguity — line shape `{allocation_id, action, quantity}` with non-negative integer quantity; unknown allocation → `ERR_ALLOCATION_NOT_FOUND` (resolved before the `SETTLED` state gate); cross-show line/bad action/bad quantity → `ERR_VALIDATION`; both money fields required non-negative — routes/shows.py:195-236.
- §3.7 Online order create — insert — ambiguity — the product must belong to the order's tour, else `ERR_CROSS_TOUR_REFERENCE` — routes/online_orders.py:63-65.
- §3.8 Void — insert — ambiguity — the record's `ACTIVE` check runs before the session-open or settlement-state gate on both void paths — routes/sale_records.py:148-160.
