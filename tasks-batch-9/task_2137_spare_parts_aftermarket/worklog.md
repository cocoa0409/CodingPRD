# Worklog — task_2137_spare_parts_aftermarket

## Step 1: Create task directory — 2026-08-22T00:00:00.000Z

Created `tasks/task_2137_spare_parts_aftermarket/` and `tasks/task_2137_spare_parts_aftermarket/workspace/` (index 2137 = highest existing 2136 + 1).

## Step 3: Copy shared files — 2026-08-22T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2137_spare_parts_aftermarket/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-22T00:00:00.000Z

Generated all three scaffold artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_2137_spare_parts_aftermarket/`, built purely from the scenario text plus the skill spec (no sibling task was read).

## Verdict block (pasted verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  798

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**Complexity profile** — `quota_allocation` × `pricing_engine`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph` (true M:N junction + self-referential supersession chain); role model `segregation_of_duties`; difficulty `expert_plus`.

**SCAFFOLD.yaml** (2252 lines, §1.0–§1.7)
- **14 entities**: Part, EquipmentModel, InstalledUnit, PartApplicability, Dealer, ServiceWorkOrder, WorkOrderPartLine, DemandForecast, LastTimeBuyCampaign, AllocationRequest, ReplenishmentOrder, ReturnAuthorization, AftermarketPriceRule, StockLedgerEntry (append-only, `common_fields: false`).
- **7 state machines**, deliberately heterogeneous: Part (branching + revert + SUPERSEDED side-branch), LastTimeBuyCampaign (**cyclic** REJECTED->DRAFT), ReplenishmentOrder (**parallel dimensions** approval x logistics with one cross-dimension guard), ReturnAuthorization (**branching fork** RESTOCK/SCRAP with divergent side-effect sets), ServiceWorkOrder (**cyclic** OPEN<->PARTS_PENDING), WorkOrderPartLine (BACKORDERED->RESERVED revert), AllocationRequest.
- **2 concurrency rules**, both true CREATE-with-supersede races resolved by OCC on the parent's `version` (`expected_part_version` on campaign create, `expected_campaign_version` on allocation-request create).
- **8 calculations**: forecast_from_work_orders (3 methods, half-open lookback window), part_criticality_and_stocking_policy, aftermarket_price_uplift (LIST vs QUOTE rounding order), emergency_air_freight_decision (4-input, 4-branch ordered), ltb_lifetime_buy_quantity (DEMAND_DECAY vs FLAT_RATE), dealer_allocation_waterfall (fair-share + waterfall, `created_at` tie-break), return_restocking_fee_and_credit (pinned 5-step order, circular-looking rebate tier), backorder_promotion_order (greedy single-pass sweep).
- **29 validations**, strictly priority-ordered; **66 endpoints** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default); **45 errors**; **5 roles** (AftermarketPlanner, InventoryController, DealerUser=`entity_backed:Dealer`, PricingAnalyst, PlatformAdmin).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids / **24 instances** (2/3/3/2/3/3/3/2/3). Highlights: LIST 12600 vs QUOTE 12597; DECAY 17 vs FLAT 30; a **depth-4 cascade** (campaign approve -> part LTB_OPEN -> re-price 1906 -> open line re-quoted 12970->13343) and a **depth-3 cascade** (consume 82 -> available 4 <= reorder 5 -> auto STOCK order qty 26); three distinct validation-priority pairs (state/fiscal, safety/referential, temporal/constraint); boundaries at score exactly 70.00, the excluded half-open window edge, and net benefit exactly 100000; two genuinely different interval geometries (integer closed with adjacency allowed vs datetime half-open with a symmetric 30-day cooldown); three conserved quantities (physical units vs ledger, campaign entitlement, dealer money).

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections / **60 instances** (50 with full recipes, 10 `excluded_because:` stubs).

Every formula-derived assertion literal was computed by executing the §1.3 formulas in Python before being written. Cross-file audit passed: zero duplicate names, all `grounds` resolve, all stub references exist in §1.8, no forbidden concurrency vocabulary, file split honored.

Two scaffold self-consistency fixes surfaced during §1.9 authoring and were applied: the supersede precondition was relaxed to `successor.lifecycle_state != OBSOLETE` (the original `IN {ACTIVE, PHASE_OUT}` made `ERR_SUPERSESSION_CYCLE` structurally unreachable), and `Part.replenishment_status` was re-pinned to a three-branch evaluation with a `reorder_point_units > 0` guard so an unclassified part reads NORMAL.

## Step 4: Generate PRD — 2026-08-22T00:00:00.000Z

PRD generated at `workspace/PRD.md` — **476 lines / 13,036 words**, built incrementally in five appends (no one-shot write), then verified mechanically.

**Structure**: §1 Introduction (3 paras) -> §2 with ten subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Properties & Path Resolution, 2.6 OCC, 2.7 Rounding Discipline, 2.8 Stock Arithmetic & Ledger, 2.9 Cascade Discipline, 2.10 Validation Precedence) -> §3 with nine domain subsections (Registry / Catalogue+Applicability / Forecasting / Classification / Pricing / Work Orders+Air-Freight / Replenishment+Promotion Sweep / Obsolescence+LTB+Allocation / Returns) -> §4 4-column endpoint table -> §5 2-column error table. No audit footer.

**Coverage tally (all verified by script against SCAFFOLD.yaml):** entities 14/14; entity fields 120/120; endpoint input/query/path identifiers 69/69; union of required backticked identifiers 128/128; state machines 7/7; all state values + enum values present verbatim; calculations 8/8 with every constant literally traceable; validations 29/29 enumerated in priority order in §2.10 with error IDs + scopes; concurrency_rules 2/2 (write_endpoint + `expected_part_version`/`expected_campaign_version` + `ERR_STALE_*_VERSION` + 412); endpoints 66/66 rows in §4; errors 45/45 rows in §5 and all 45 also in §1–§3 narrative; roles 5/5.

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body/input: 69 required, 69 present, 0 missing
- endpoints[].query_params: included above (limit/offset + all filters), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose (ordered list, §2.10), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ_field + error_id + 412), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed (from/to, preconditions->error_id, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose, no pseudocode, no fuzzy words, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in narrative, 0 missing
- endpoints[].side_effects / applies_to: 66 checked, 66 expressed, 0 missing
- entities[].fields[] structured content: 120 checked, defaults/types/initials reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (ACTIVE->SUPERSEDED vs PHASE_OUT->SUPERSEDED; RESTOCK vs SCRAP inspect;
  LIST vs QUOTE pricing; DEMAND_DECAY vs FLAT_RATE; 3 forecast methods; approval vs logistics dimensions),
  6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 948
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was pasted byte-identically from `section-2.2-response-structure.md` (verified by substring match). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Two things worth flagging for downstream steps: (1) the scaffold does not state the initial `version` value, so the PRD pins it at 1 incrementing by exactly 1 per mutation — the implementation and tests must agree; (2) `StockLedgerEntry` is the only entity with `common_fields: false`, and the PRD says explicitly that it carries only `id` and `created_at`, with no `updated_at` and no `version`.

## Step 6: Generate implementation — 2026-08-22T00:00:00.000Z

The implementation is complete and verified.

## What was built

`workspace/implementation/` — Python 3 + Flask, ~3,200 lines across 12 modules:

- `start.sh` — guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts only + logical clock (default `2026-08-01T00:00:00Z`, never reads wall clock); **no seeding anywhere**
- `envelope.py` / `errors.py` / `auth.py` — `meta`/`response_type`/`data` envelope, the 45-code catalogue, `X-User-ID`/`X-User-Role` auth, input + pagination validators
- `calc.py` — all 8 calculations in `Decimal` with pinned rounding (`ROUND_HALF_UP`/`CEILING`/`FLOOR`)
- `domain.py` / `serializers.py` — lookups, ledger, re-quote cascades, promotion sweep, applicability coverage
- `routes/` — 8 blueprints covering all 66 endpoints

## Key fidelity decisions

- **`available_units` and `replenishment_status` are derived at serialization time** from the pinned 3-rule order, so they can never drift and never cause a spurious `version` bump.
- **Validation precedence** follows PRD §2.10 literally per endpoint (e.g. hazmat priority 11 fires *before* superseded priority 12; margin floor 27 before credit hold 29). Priority 3 (dealer scope) needs its target resolved, so path/FK resolution runs immediately before it — except on `POST /allocation-requests`, where the body `dealer_id` is scope-checked before FK resolution as declared.
- **Classify's 14-vs-24 circularity** (rule check outranks forecast check, but the new band needs the forecast) is resolved by checking the *current* band's rule when no forecast exists, then the *new* band's rule after computing it — satisfying both orderings.
- **`version` bumps follow PRD prose, not scaffold side-effect lists** where they disagree — e.g. adding a `BACKORDER` line does not bump the part's version (only the `STOCK` branch does); withdrawing a `PENDING` allocation request does not bump the campaign's version.
- `created_at`/`updated_at`/`api_request_timestamp` all read the logical clock; list ordering breaks created_at ties with a hidden monotonic sequence so creation order is stable.
- A global RLock wraps every request (`before_request`/`teardown_request`) so multi-step mutations are atomic under concurrent clients.

## Verification

Five smoke suites (~120 assertions) run against fresh boots, all passing, covering: LIST/QUOTE rounding divergence (1333 @ 0.35 x 7 -> 12600/12597, delta +3), air-freight branch order and the PLATINUM override, auto-generated `EMERGENCY_AIR` and `STOCK` replenishment cascades, the greedy skip-and-continue promotion sweep (large `MACHINE_DOWN` passed over for a smaller `DEGRADED`), the two-pass allocation waterfall with fair share and priority ranking, `DEMAND_DECAY` vs `FLAT_RATE` divergence, LTB half-open overlap vs 30-day cooldown, RMA five-step credit with the money-conservation invariant, the RESTOCK/SCRAP ledger fork, OCC 412s, SoD 403, credit-hold 402, supersession cycles, and 6-way concurrent reservation against 3 units of stock.

Two "failures" in my scratch scripts were bad test expectations, not code bugs — both confirmed correct against the PRD (hazmat outranks superseded; a 4-unit line against 5 available legitimately reserves).

## Step 5: Generate unit tests — 2026-08-22T00:00:00.000Z

Complete. Test infrastructure and suite generated for task 2137.

## What was produced

**`test_helpers/`** (1,922 lines, 9 files) — `types.py` (entity TypedDicts + 24 status enums; `StockLedgerEntry` correctly omits `updated_at`/`version` per `common_fields: false`), `api_client.py` (all 63 endpoints), `api_errors.py` (45 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity assertions plus domain invariant checkers: stock arithmetic, credit-hold derivation, LIST/QUOTE variant identity, return credit chain, campaign entitlement conservation, ledger-balances-stock), `factories.py`, `constants.py`, `test_users.py` (with `make_dealer_headers(dealer_id)` for the `entity_backed:Dealer` role, plus per-instance builders for the segregation-of-duties operators), and `fixtures.py` (5 tiers: primitives -> `receive_stock`/`ship_stock_order` -> `setup_catalogue`/`setup_scenario_with_work_order` -> `setup_consumed_line`/`setup_received_rma` -> `setup_approved_campaign`/`drive_part_to_obsolete`).

**`test_suite/`** (3,719 lines, 10 files + conftest) — **98 tests**, all collected cleanly by pytest.

## Coverage against the design-index contract

- **Queue A**: all 24 difficulty instances x exactly 2 tests = 48 tests.
- **Queue B**: all 50 non-stub corner instances x 1 test = 50 tests. The 10 `excluded_because:` stubs were not translated; every one of their `difficulty_instance:` cross-references was verified to resolve.
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, verbatim from the source YAML.
- Every PRD quote was machine-checked to survive a literal whitespace-normalized grep of `PRD.md` (one quote was reflowed after the checker caught a hyphen split across a line break).
- No `skip`/`skipif`/`xfail`; no scaffold references leak into the generated code.

A verifier script re-runs all four checks (Design-tag validity, stub non-translation, verbatim citation, >=2/>=1 coverage) and reports **ALL CHECKS PASS**.

## Key findings worth flagging

**One corner instance has an unreachable fixture.** `Corner/state_machines/campaign_close_denies_pending_allocation_requests` sets up a second `AllocationRequest` created *after* the allocation run, i.e. while the campaign is `ALLOCATING`. PRD §3.8 states plainly that "The campaign must be in `APPROVED`" for allocation-request creation (§2.10 rule 9 repeats it), so a faithful implementation rejects that create with `ERR_CAMPAIGN_STATE_INVALID`. Since the allocation run resolves *every* PENDING candidate (suspended dealers included go straight to `DENIED`), **no reachable state has a PENDING request on an ALLOCATING campaign** — the "close denies pending requests" branch is dead code under this PRD. The test covering the instance's reachable assertions was emitted (campaign -> `CLOSED`, the awarded request untouched at 5 units, `remaining_qty` 15 with the entitlement invariant holding, part -> `LTB_CLOSED`, and the cascaded re-price being a no-op with no active rule) and only the unreachable `ar2 == DENIED` assertion was dropped. This is a corner-design bug, not a test bug.

**All pre-computed literals in both indices independently re-derived and confirmed** against the PRD formulas — including the 12600/12597 LIST-vs-QUOTE divergence and its sign flip to -1 at uplift 0.43, the 37-vs-30 decay/flat LTB split, `criticality_score` landing on exactly 70.00, the 11190000 and exactly-100000 air-freight net benefits, the 53/36/0 waterfall scores producing 60/24/16, and the 497999 -> 9960 rebate keyed on the pre-rebate net.

## Step 7: Run tests and iterate — 2026-08-22T00:00:00.000Z

The exit condition is met on the first iteration. No changes were needed.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep; the exit condition was met immediately).

**Result:** all 8 concurrent rounds passed `98/98` — `failed: 0`, `errors: 0`, `skipped: 0` in every round, ~131s wall time per round. No test failed in any round, so the union of failing tests across the sweep is empty and the diagnostic protocol (STEP 0 -> STEP 3) never had to be entered.

**Tests deleted:** none. No test failed either the PRD-coverage (STEP 1a) or unique-derivability (STEP 1b) check, because no test failed at all.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

### Integrity checks performed alongside the sweep

- **No flakiness masking.** All 8 rounds ran to completion concurrently with no early exit; the port registry (`~/.cache/prd-bench-local-runner/ports.tsv`) gave each round its own port, so there were no default-port collisions. Every round produced an identical 98/98 result, so no test is passing on luck.
- **No forbidden weakening.** `grep` for `skip` / `xfail` across `test_suite/` and `test_helpers/` returns only substring matches inside test names and docstrings describing the greedy backorder-promotion sweep (`..._sweep_is_greedy_and_skips_the_oversized_line`) — there are no `pytest.mark.skip` / `xfail` markers anywhere.
- **No seeded state.** `workspace/implementation/store.py` is in-memory dicts only; no SQLite file, no JSON dump, no `/tmp` cache, no startup entity registration. The only `open(`/`seed` hits are comments stating the store boots empty.
- **Test-count integrity.** 98 `def test_` functions across the 10 suite files, matching the 98 reported by the runner — nothing was silently dropped from collection.

Two implementation details already in place are what keep the sweep stable under 8x concurrent load, and both are worth preserving: `start.sh` guards its `pip install` behind an `import flask` check (an unconditional install per per-test reboot causes boot-timeout flakiness), and `app.py` wraps every request in a global `RLock` so multi-step cascades stay atomic.

## Step 8: Finalize PRD — 2026-08-22T00:00:00.000Z

SKIPPED per the skill's skip condition: Step 7 exited on the first 8-round sweep with 0 iterations beyond baseline, 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD_FINALIZED.md` is intentionally absent; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-22T00:00:00.000Z

`workspace/PRD_COMPLETED.md` written (started from `workspace/PRD.md`, since Step 8 was skipped and no `PRD_FINALIZED.md` exists).

**Line counts / delta:** PRD.md 476 lines / 92,114 bytes -> PRD_COMPLETED.md 476 lines / 95,728 bytes (**+3,614 bytes**, +3,582 chars). No lines added or removed — every change is an in-paragraph insert or revision. §5 error table intact, last row `ERR_DEALER_CREDIT_HOLD | 402`.

**Counts:** 25 changes — **22 ambiguity-pins**, **3 mismatch-revisions**.

### Changes

- §2.1 — insert — ambiguity — a blank/whitespace-only `X-User-ID` counts as absent for `ERR_UNAUTHENTICATED` — `auth.py:22`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 random uppercase alphanumerics; `api_request_timestamp` reads the **logical** clock, not wall time — `envelope.py:14,20`
- §2.3 — insert — ambiguity — negative `offset` and non-integer `limit`/`offset` are `ERR_INVALID_REQUEST` 400; empty-string values treated as absent — `auth.py:166-181`
- §2.3 — insert — ambiguity — all list orderings take server-side insertion order as final tie-break (asc for oldest-first, desc for the forecast history) — `store.py:124`, `parts.py:305,383`
- §3.1 — insert — ambiguity — duplicate `model_code`/`serial_number`/`dealer_code` -> `ERR_INVALID_REQUEST` 400 — `domain.py:87-90`
- §3.1 — insert — ambiguity — decommission is not state-guarded; re-applying succeeds and advances `version` — `registry.py:109-115`
- §3.1 — insert — ambiguity — balance adjustment: both `amount_cents` and `reason` required, `reason` non-empty — `registry.py:229-230`
- §3.1 — insert — ambiguity — suspend is not state-guarded either — `registry.py:238-243`
- §3.2 — insert — ambiguity — duplicate `part_number` -> `ERR_INVALID_REQUEST` 400 — `parts.py:35`
- §3.2 — insert — ambiguity — applicability withdraw is not state-guarded — `registry.py:183-189`
- §3.3 — insert — ambiguity — with a part covering multiple models, the single `qty_per_unit` used is the covering row of the **earliest-created** covered unit; empty covered set => multiplier 0 — `parts.py:331-335`
- §3.4 — revise — **mismatch** — classify with no `CURRENT` 12-month forecast raises `ERR_PRICE_RULE_NOT_FOUND` when the part's *current* band has no `ACTIVE` rule (priority 14 outranks 24), `ERR_FORECAST_INPUT_EMPTY` otherwise — `parts.py:122-128`
- §3.5 — insert — ambiguity — `max_uplift_pct` must be zero or more — `pricing.py:23`
- §3.5 — insert — ambiguity — price-quote `qty` is a required query param, integer >= 1, else `ERR_INVALID_REQUEST` — `pricing.py:69-77`
- §3.6 — insert — ambiguity — auto `EMERGENCY_AIR` order snapshots `unit_cost_cents` and sets `total_landed_cost_cents = unit_cost x qty + freight`; the part's `version` does **not** advance on the `AIR_FREIGHT`/`BACKORDER` branches — `work_orders.py:182-196`
- §3.6 — insert — ambiguity — on consume the line's own status is checked before the parent work order's — `work_orders.py:240-243`
- §3.6 — insert — ambiguity — auto `STOCK` order has `freight_cost_cents` 0, snapshots `unit_cost_cents`, `total_landed_cost_cents = unit_cost x qty` — `domain.py:311-319`
- §3.7 — insert — ambiguity — rejecting an order advances only the order's `version`; the part's does not — `replenishment.py:111-126`
- §3.8 — insert — ambiguity — a successor in `OBSOLETE` -> `ERR_PART_LIFECYCLE_INVALID` — `parts.py:239-240`
- §3.8 — insert — ambiguity — supersede syncs parent work orders out of `PARTS_PENDING`, and does **not** re-price the part (catalogue price fields unchanged, lines cancelled not re-quoted) — `parts.py:254-268`
- §3.8 — revise — **mismatch** — obsoleting recomputes **both** `current_effective_uplift_pct` and `current_list_unit_price_cents` (PRD named only the latter), and does **not** re-quote open lines — `parts.py:289`
- §3.8 — insert — ambiguity — submit with the part outside `PHASE_OUT` -> `ERR_PART_LIFECYCLE_INVALID`, checked after the campaign's `DRAFT` state and before the windows — `campaigns.py:133-139`
- §3.8 — insert — ambiguity — the `PHASE_OUT`->`LTB_OPEN` hop on approval is conditional; a part elsewhere is left untouched — `campaigns.py:167-170`
- §3.8 — revise — **mismatch** — campaign `rejection_reason` is **required** (non-empty string), unlike the optional one on replenishment/return reject — `campaigns.py:184`
- §3.8 — insert — ambiguity — when `ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS` fires, suspended dealers' requests stay `PENDING` (the DENIED sweep only runs on a proceeding run) — `campaigns.py:248-254`

### Notes
- Verified-as-already-pinned (no change): the full §2.10 precedence ladder as realised in each route, both pricing rounding variants, the fulfilment-mode branch order, the greedy promotion sweep and its 3-key sort, the allocation two-pass waterfall and its sort keys, the five-step return credit chain, the RESTOCK/SCRAP ledger asymmetry, `available_units`/`replenishment_status` derivation, all §4 role lists, and the whole §5 error/status mapping (`errors.py:12-58` matches the table row for row).
- Every replacement was uniqueness-asserted against the source before applying (script aborts on 0 or >1 matches), so no edit landed in an unintended paragraph.
