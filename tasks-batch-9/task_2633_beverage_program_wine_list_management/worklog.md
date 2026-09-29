# Worklog — task_2633_beverage_program_wine_list_management

## Step 1: Create task directory — 2026-09-03T22:39:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2633_beverage_program_wine_list_management` and its `workspace/` subdirectory. Index 2633 was pre-assigned by the invoker (no auto-allocation scan performed, per instruction — up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T00:12:00.000Z

All three scaffold artifacts for task 2633 are complete, parse as YAML, and pass `scaffold_lint.py` with a clean verdict.

Output directory: `/home/ubuntu/github/CodingPRD/tasks/task_2633_beverage_program_wine_list_management/`

- `SCAFFOLD.yaml` — 3,378 lines. Top-level keys exactly §1.0–§1.7 (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `constants_global`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`); neither `scaffold_difficulty_design` nor `scaffold_corner_design` present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,845 lines, single top-level key.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,598 lines, single top-level key.

Counts

- Entities: 15. Endpoints: 69 (API prefix `/beverage-program`, plus the `/_clock/set_current_utc` driver). State machines: 5 (incl. AllocationOffer with parallel `fulfillment_state` × `compliance_state`). Calculations: 14. Ordered validations: 63 (single global priority ladder). Errors: 71. Roles: 5 (BeverageDirector, VenueSommelier, DistributorRep, Controller, ComplianceOfficer). OCC rules (§1.2.1): 2.
- Complexity profile: `quota_allocation` × `pricing_engine`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `expert_plus`.
- §1.8: 9 rules × 2 = 18 instances, all with full `test_recipe`.
- §1.9: 77 instances across all nine guide sections — entities 12, state_machines 14, calculations 11, validations 14, endpoints 5, errors 9, rbac 6, cross_cutting_complexity_layers 4, consistency_model 2. Of these, 61 carry executable `test_recipe` chains and 16 are `excluded_because` stubs whose cited §1.8 instance names all resolve (0 dangling).
- Lint coverage: 926 setup/trigger calls scanned across §1.8+§1.9; all conform to §1.5 (endpoint, role, payload keys, captures, OCC `${var}` discipline) and every §1.1 FK is reverse-reachable.

Audits run

- Error triggerability: all 71 error ids appear in at least one §1.8/§1.9 instance — 0 uncovered.
- Name uniqueness across the union of both design files: 0 duplicates.
- Per-instance contract: every instance has `name`, `claim_type`, `grounds`; every non-stub has `distinguishing_aspect` plus `test_recipe.{setup, setup_api_calls, trigger, assert}`; no stub carries a `test_recipe`.
- One SCAFFOLD.yaml self-consistency fix was applied during generation: the `POST /venues/{venue_id}/pour-cost-runs` side effect described posture boundaries as inclusive ("at or above"), contradicting §1.1 `Venue.program_posture` and §1.3, which use strict `>`; the endpoint text now states the strict boundaries (OPEN ≤ 3.00, RESTRICTED > 3.00 and ≤ 6.00, FROZEN > 6.00 or any ESCALATED investigation).
- No sibling task directory was listed, read, or grepped; the scaffold was derived solely from the scenario text and the skill's own SKILL.md plus `references/claim-extraction-guide.md`.

Orchestrator verification: workspace/ and worklog.md survived Step 2 intact; all three YAML files present with expected line counts.

## Step 3: Copy shared files — 2026-09-04T00:12:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T00:31:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **481 lines** (103,742 bytes), written in 11 incremental `cat >>` heredoc appends (no giant Write). Ends cleanly on the final row of the §5 error table (`ERR_NO_REVENUE_IN_PERIOD | 422`), a completed section boundary.

**Section list (25 headings):**
- §1 Introduction
- §2 Global Specifications: 2.1 Roles/RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties and the Append-Only Ledger · 2.6 Money, Percentages and Rounding · 2.7 Version Guards on Offers and Draft List Versions · 2.8 Path Resolution and the Order of Validation (22-step ordered list) · 2.9 Conservation of Bottles and of Money · 2.10 Fiscal Posture
- §3 Business Logic: 3.1 Venues/Cellar/Catalogue · 3.2 Licence Standing and the Two Offer Dimensions · 3.3 Allocation, Waterfall, Receipt · 3.4 Composing a List: Drafts, Entries, Pricing · 3.5 Review, Publication, Supersession · 3.6 Vintage Changes, Staleness, Reprints · 3.7 The By-the-Glass Rail · 3.8 Spoilage Write-Offs, Lot Lifecycle, Reversals · 3.9 Wine Dinner Events · 3.10 Cost Governance (pour cost, investigations, par, corkage)
- §4 Endpoint Definitions (intro + 69-row, 4-column table)
- §5 Error Code Catalogue (71-row table)

**Coverage verified mechanically against SCAFFOLD.yaml:**
- Endpoints: **69 / 69** exact path strings present in the §4 table.
- Error ids: **71 / 71** present, and all 71 also referenced in §2/§3 prose; every `(HTTP nnn)` citation in prose matches the scaffold's `http` value (0 mismatches).
- Calculations: **14 / 14** expressed in prose (incl. `list_entry_contest_points` weights 1/3/5/10 and the 4-decimal clamped margin factor, `btg_slot_occupancy_check` closed-closed zero-buffer geometry, `par_reorder_quantity` strict-`<` half-par ceiling, `corkage_charge` floor-division waiver). Snake_case calc names deliberately do not appear — the skill forbids pseudocode identifiers in prose.
- Entities: **15 / 15** covered (as natural-language names plus all their fields in backticks).
- Validations: **59** in the scaffold (the Step 2 summary said 63); all 59 priorities 1–63 are encoded in §2.8's ordered list, in exact priority order (stale-version before state preconditions; segregation of duties at 39, after state, before compliance).

**Hard Contracts:**
1. **Field-Name Coverage — PASS.** 143 required identifiers extracted from `entities[].fields[].name`, `input`, `query_params` and path params; 143 appear inside backticks.
2. **Rule Coverage — PASS.** Both OCC guards (`expected_offer_version`, `expected_list_version_version` → `ERR_STALE_VERSION` 412) in §2.7; all state transitions, cross-entity cascades (compliance review → offer dimensions; receipt → bin/availability; write-off approval → ledger/lot/bin/entry/slot; settlement → lots/venue ledgers), sibling-branch symmetry (`GRANTED`/`PARTIALLY_GRANTED` receive branches identical; four resolve transitions), and `applies_to` scoping all in §3.
3. **§3 Path Purity — PASS.** 0 backtick tokens in §3 start with `/`, are a bare HTTP method, or combine method+path.

The constraint was honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced.

Two notes from the generator: (a) the scaffold names the RBAC error `ERR_FORBIDDEN_ROLE`, not `ERR_ROLE_NOT_PERMITTED` — an early draft slip was corrected repo-wide in the file; (b) scaffold-internal conflicts adjudicated in favour of the state-machine section are the BtgSlot close boundary (clock ≤ `preservation_expires_at` closes normally) and the `EXPLAINED` investigation resolution (posture recomputed from `last_variance_pct` rather than left untouched); the reprint/supersession cascade instead follows the broader endpoint reading (`PLANNED`, `PRICED`, `CONFIRMED`).

Orchestrator truncation check (per invoker's guard): `tail -25` confirms the file ends on a complete error-table row and `grep '^#'` shows all 25 headings present through §5. NOT truncated — no regeneration needed.

## Step 5/6 launch note — 2026-09-04T00:33:00.000Z

Steps 5 (unit-test generator) and 6 (implementation generator) were launched as concurrent background subagents. Orchestrator note on isolation: the two Agent calls landed in back-to-back messages rather than one message, so the skill's "single assistant message" letter was not met — but the *purpose* of that rule (physical isolation of the impl generator from `test_suite/`) was verified to hold empirically. An `ls -la` of the task root taken immediately after the impl generator launched shows only SCAFFOLD*.yaml, worklog.md and workspace/ — neither `test_helpers/` nor `test_suite/` existed on disk at that instant, so Step 6 could not have read the tests even had it tried. Step 6 was additionally given an explicit hard constraint forbidding any read of those directories.

## Step 5: Generate unit tests — 2026-09-04T01:05:00.000Z

Complete. All infrastructure and tests are generated and verified.

## Files written (all at the TASK ROOT, nothing inside `workspace/`)

**`test_helpers/`** — 1,715 lines
`types.py` 428 · `api_client.py` 258 (one method per PRD endpoint, `api_client` singleton) · `api_errors.py` 152 (all 71 error ids + status map, auto-registered on import) · `fixtures.py` 384 · `factories.py` 223 · `assertions.py` 96 · `test_users.py` 85 (entity-backed header builders for `VenueSommelier`/`DistributorRep`) · `constants.py` 67 · `__init__.py` 22

**`test_suite/`** — 8,836 lines, `conftest.py` + 18 test modules
Queue A: `test_01_dual_variant_calculations` 388 · `test_02_combinatorial_pricing_formulas` 287 · `test_03_non_linear_state_machines` 289 · `test_04_transitive_cascades` 439 · `test_05_validation_priority_conflicts` 269 · `test_06_boundary_precision` 222 · `test_07_cross_entity_state_dependency` 304 · `test_08_resource_temporal_overlap` 277 · `test_09_compensating_invariants` 336
Queue B: `test_10_entity_records` 794 · `test_11_state_transitions` 799 · `test_12_calculation_corners` 459 · `test_13_validation_rules` 1177 · `test_14_endpoint_behaviour` 545 · `test_15_error_catalogue` 1062 · `test_16_role_permissions` 729 · `test_17_concurrency_and_layers` 270 · `test_18_consistency_model` 169

## Verification (all green)

- **254 test functions**, `pytest --collect-only` → 254 collected, 0 errors; `py_compile` clean on all 28 .py files.
- **Design tags: 254 tags, 254 tests** — exactly one per test, zero untagged, zero dual-tagged, zero pointing at a non-existent or stub instance.
- **Coverage: 79 / 79 non-stub instances translated, 0 skipped.** The 16 `excluded_because` stubs (5 state_machines, 6 calculations, 2 validations, 2 cross_cutting, 1 consistency_model) correctly received no tests, and each of their `difficulty_instance` cross-references resolves.
- **PRD citations: 276 docstring quotes, all present verbatim in `workspace/PRD.md`** (whitespace-normalised substring check).
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. No stray `.md`/`.bak` files; `__pycache__` cleaned.

## Findings worth the PRD author's attention

Six yaml literals were judged to contradict the PRD; in each case the PRD was followed and the instance still translated:
1. `reason_code: "SPOILAGE"` appears in four recipes — `SPOILAGE` is a *ledger reason*, not one of the five declared write-off reason codes, so those setups would die at `ERR_INVALID_ENUM_VALUE`. Substituted with a declared member.
2. `ERR_SLOT_NOT_OPEN` asserted as HTTP 422; the PRD and catalogue both say 409.
3. `AllocationClaim.granted_bottles == null` on a `REQUESTED` claim; the PRD says it is created at `0`.
4. `Venue.last_variance_pct is null`; the PRD says it starts at `0.00`.
5. `Distributor.last_reviewed_at` is asserted but no such field exists in the PRD.
6. `contest_points == 0.00` before any ledger row on an `education_verified: true` entry; the PRD's +5 rule makes it `5.00` (and another corner instance asserts 5.00, so the yaml is self-inconsistent).

Three yaml assertions failed unique-derivation and were dropped without weakening the surrounding test: `raw_share == 6.0000` on an under-subscribed claim (formula gives 10.0000 and applies only to the proration branch), `settled_cogs_cents == 0` before settlement (PRD only says a void resets it to null), and `spoiled_pours == 3` on the expiry-*sweep* path (the PRD sets that only on the close-after-expiry branch).

One genuine internal PRD tension: §2.8 rung 18 orders the compliance sub-checks *distributor hold → offer block*, while §3.3's prose lists *offer block* first. Both apply in `business_safety_beats_business_constraint_on_allocation_receipt`, so an implementer following §3.3's prose order returns `ERR_OFFER_COMPLIANCE_BLOCKED` and fails that test. The test follows §2.8, which §5 designates as the authoritative tie-breaker — but one clarifying clause in §3.3 would remove the ambiguity.

The suite was never executed against a live server: `workspace/implementation/` was still being written by the concurrent implementation generator, so validation is static (compile + collect + tag + citation) only.

## Step 6: Generate implementation — 2026-09-04T01:05:30.000Z

Implementation complete and verified.

## Files written (all in `workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `core.py` | 577 | logical clock, empty in-memory `Store`, 71-entry error→HTTP table, envelope helpers (`meta`/`response_type`/`data`), auth + scope checks, ordered body-validation passes, pagination, per-type lookup helpers |
| `calc.py` | 480 | all 14 calculations (markup tiers, bottle/glass pricing, price bands, preservation expiry, FIFO vs WEIGHTED_AVERAGE draws, BTG three-bucket split, contest points, `Fraction` allocation waterfall, event pricing, corkage, pour-cost variance, par levels) |
| `cascade.py` | 287 | bin occupancy, availability/OOS + stale recounts, reprint escalation, pinned-event staleness, append-only ledger writer, venue ledger totals, posture recompute, lot depletion |
| `routes_master.py` | 341 | venues, cellar bins, distributors, compliance reviews, wines |
| `routes_alloc.py` | 409 | offers, claims, allocate, withdraw, receive, direct lots, depletion-entry reads |
| `routes_lists.py` | 426 | wine lists, versions (submit/request-changes/publish/mark-reprinted/archive), list entries + PATCH |
| `routes_ops.py` | 431 | BTG slots (open/close, occupancy sweep) and spoilage write-offs (submit/approve/reject/reverse with the full transitive cascade) |
| `routes_events.py` | 344 | wine dinners: create (window buffer geometry), price, confirm, settle (pre-checked atomic draw), void-settlement, cancel |
| `routes_reports.py` | 265 | pour-cost runs and report, par report, investigations (escalate/resolve), corkage quote, `POST /_clock/set_current_utc` |
| `app.py` | 66 | blueprint registration, `ApiError`/404/405/500 envelope handlers, `0.0.0.0:$PORT` |
| `start.sh` | 9 | guarded `pip install` (only when flask missing) + `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0.0` |

## Endpoint coverage
Programmatically diffed the Flask URL map against `SCAFFOLD.yaml`: **69/69 endpoints present, 0 missing, 0 extra.**

## Verification performed
- `python3 -m py_compile` on all 10 modules: clean.
- Booted `PORT=21633 bash start.sh`, ran a 40-call end-to-end happy path (venue → bin → distributor → clearance → wine → offer → claim → waterfall → receipt → list → entry → submit → publish → BTG slot open/close → write-off approve/reverse → event price/confirm/settle/void/cancel → pour-cost run → report → par report → investigation escalate/resolve → corkage): **0 failures**, and the arithmetic matched hand-checks against the PRD (bottle 14400/PREMIUM, glass 3125, BTG split 3000/1000/0 with 9375 revenue, event 1334→4500→4500→29.64%, settlement 16000/45000, variance 42.67−34.94=7.73 → FROZEN + auto-investigation).
- Ran a second 60-call negative-path sweep: `ERR_STALE_VERSION` 412, `ERR_DUPLICATE_CLAIM`, `ERR_OFFER_NOT_OPEN`, `ERR_RECEIVED_AT_IN_FUTURE`, `ERR_BIN_ZONE_MISMATCH`, `ERR_BIN_CAPACITY_EXCEEDED`, `ERR_POUR_SIZE_REQUIRED` 400, `ERR_POUR_SIZE_TOO_LARGE`, `ERR_SLOT_OCCUPIED`, `ERR_POURS_EXCEED_BOTTLE`, `ERR_EVENT_WINDOW_CONFLICT` (plus the 120-minute adjacency case correctly *accepted*), `ERR_NO_REVENUE_IN_PERIOD`, `ERR_BYO_LIMIT_EXCEEDED`, etc. — **no 5xx responses at all**.
- Fresh boot after clearing `__pycache__`: `GET /venues` returns `total_count: 0`, confirming the store is empty on every launch (no seeding anywhere).
- Both servers killed by their own listening PID (`ss -ltnp` → `kill <pid>`); no broad `pkill` used; ports confirmed free afterwards.

Two decisions worth flagging: (1) the clock endpoint returns HTTP 204 as PRD §4 mandates — Werkzeug unconditionally strips bodies from 204 responses, and forcing one back in would desynchronise keep-alive clients, so the envelope is not transmitted for that one route; (2) where PRD §3 prose lists preconditions in a different order than §2.8's 22-step precedence, I followed §2.8 except where §3 says "in this order" explicitly (write-off approval), which §2.8 itself defers to.

## Step 7: Test-and-fix loop — 2026-09-04T02:00:00.000Z

Two parallel 8-round stability sweeps (`--isolation per-test-server`, 254 tests/round, all rounds under `setsid nohup`).

**Iteration 1** — 249/252/250/250/250/251/250/252 passed of 254. Union of failures across the 8 rounds: 5 tests, 2 root causes.

**Iteration 2** — 254/254 in all 8 rounds. Clean.

### Root cause 1 — `test_helpers` re-sorted collections by `id` (3 flaky tests)

`assertions.depletion_entries_for` and `fixtures.open_investigations` re-sorted the server's response with `key=(created_at, id)`. Every ledger row a single slot closure writes shares one `occurred_at` and one `created_at` (both taken from the logical clock at that instant), so the tie-break fell through to a random UUID and the asserted bucket order (`SALE_BTG`, `STAFF_EDUCATION`, `SPOILAGE`) came back shuffled at random — hence the 2/8 and 5/8 failure rates. PRD §2.3 states "Records are never ordered by `id`" and pins the ledger's order as `occurred_at` ascending then `created_at` ascending, which the server already emits. Both helpers now return the server's order unmodified.

Affected: `test_a_sum_exactly_equal_to_the_bottle_closes_with_no_spoilage`, `test_the_spoilage_bucket_absorbs_the_rounding_remainder`, `test_the_freezing_run_pins_the_variance_and_opens_one_investigation`.

### Root cause 2 — allocation receipt ran the two compliance checks in §3.3's prose order (2 hard failures)

`routes_alloc.receive_claim` tested the offer's `BLOCKED` dimension before the distributor's `HOLD` standing, following §3.3's enumeration of the six receipt guards. §2.8 rung 18 fixes the order as "distributor hold, offer block, prohibited by-your-own-bottle category", and §2.8 plus §5 both designate that ladder as the authority whenever several errors could apply to one request ("The relative order above is what disambiguates a request that violates two rules at once"). §3.3 does not claim its list is ordered. The two checks are now swapped, so a receipt from a held distributor whose offer is consequently blocked reports `ERR_DISTRIBUTOR_COMPLIANCE_HOLD`.

Affected: `test_licence_hold_answers_before_the_bin_capacity`, `test_bin_capacity_surfaces_once_the_licence_is_cleared_again`.

No tests were deleted, weakened, skipped or xfailed; no assertion was downgraded from an `error_id` check.

## Step 7: Run tests and iterate (orchestrator record of subagent's returned summary) — 2026-09-04T01:53:00.000Z

All 8 rounds green: 254/254 in every round.

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, 254 tests/round, under `setsid nohup`).

- Iteration 1: 249/252/250/250/250/251/250/252 of 254 — union of 5 failing tests, 2 root causes.
- Iteration 2: 254/254 in all 8 rounds, ~447s per round.

**Tests deleted:** none. Both root causes traced to verbatim PRD sentences, so every test passed STEP 1a/1b.

**Fixes applied to `test_helpers/`** (STEP 2 — fixture inconsistent with PRD):

- `test_helpers/assertions.py` — `depletion_entries_for()` re-sorted the server's response with `key=(created_at, id)`. All ledger rows written by one slot closure share a single `occurred_at` *and* `created_at` (both from the logical clock), so the tie-break fell through to a random UUID and the asserted bucket order came back shuffled — the source of the 2/8 and 5/8 flake rates. PRD §2.3: "Records are never ordered by `id`", and the ledger's order is pinned as `occurred_at` asc then `created_at` asc, which the server already emits. Now returns the server order unmodified.
- `test_helpers/fixtures.py` — `open_investigations()` had the same `(created_at, id)` re-sort; same fix.

Those two fixed `test_a_sum_exactly_equal_to_the_bottle_closes_with_no_spoilage`, `test_the_spoilage_bucket_absorbs_the_rounding_remainder`, and `test_the_freezing_run_pins_the_variance_and_opens_one_investigation`.

**Fixes applied to `implementation/`** (STEP 3):

- `workspace/implementation/routes_alloc.py`, `receive_claim()` — swapped the two compliance-safety checks so the distributor `HOLD` test runs before the offer `BLOCKED` test. The implementation had followed §3.3's prose enumeration of the six receipt guards; §2.8 rung 18 fixes the order as "Compliance safety: distributor hold, offer block, …", and both §2.8 ("The relative order above is what disambiguates a request that violates two rules at once") and §5 designate that ladder as the authority when several errors apply at once, while §3.3 never claims its list is ordered. Fixed `test_licence_hold_answers_before_the_bin_capacity` and `test_bin_capacity_surfaces_once_the_licence_is_cleared_again`.

Worth flagging to the PRD author: §3.3's receipt-guard sentence lists offer-block before distributor-hold, the reverse of §2.8 rung 18. The precedence is resolvable (§2.8/§5 are explicitly the tie-breaker), but one clarifying clause in §3.3 would remove the ambiguity entirely.

No assertion was weakened, no `skip`/`xfail` added, no `error_id` check downgraded, and no PRD-required implementation check removed.

**Orchestrator independent verification:** all 8 `results.$i.json` files exist on disk (timestamps 01:31) and each parses to `passed=254 total=254 failed=0`. The clean sweep is confirmed from the per-round result files, not from the subagent's claim or from the spliced `sweep.log`.

**Step 8 skip condition NOT met** (2 `test_helpers/` fixes + 1 `implementation/` fix), so Step 8 will run.

## Step 8: Finalize PRD — 2026-09-04T01:46:00.000Z

`PRD_FINALIZED.md` is written at `workspace/PRD_FINALIZED.md`.

## Size

- PRD.md: 481 lines / 103,742 bytes
- PRD_FINALIZED.md: 481 lines / 104,283 bytes
- Line delta: 0 (+0.0%); byte delta: +541 (+0.52%). Two lines revised in place (84, 201); no new sections, no reordering.

## Changes

- **§2.3 Pagination** — insert (appended to the existing ordering sentence, nothing removed) — pins the residual tie-break that PRD left open: when rows tie on every ordering key a collection names (common, because the logical clock stamps one operation's rows with the same `created_at`, and one operation's ledger entries with the same `occurred_at`), they come back in server write order, oldest write first — with the slot-closure bucket trio named as the concrete consequence. Impl: `routes_alloc.py:411`, `core.py:272,300-305`.
- **§3.3 receipt guards** — revise — swapped the distributor-`HOLD` and offer-`BLOCKED` clauses so the enumeration reads hold-then-block, and stated that the list is in evaluation order, matching the §2.8 ladder. This removes the §3.3-vs-§2.8-rung-18 contradiction Step 7 flagged. Impl: `routes_alloc.py:300-315`.

## Pre-edit search log

**Edit 1 — §2.3 residual ordering**
- (a) Subject: the final tie-break applied to every collection response (and therefore to any nested/derived row list), triggered by the `test_helpers/assertions.py` `depletion_entries_for()` and `test_helpers/fixtures.py` `open_investigations()` re-sort fixes.
- (b) Paths enumerated: every `paginate(...)` callsite (`routes_master.py:116,175,220,340`; `routes_alloc.py:100,204,384,412`; `routes_lists.py:88,147,372`; `routes_ops.py:147,319`; `routes_events.py:171`; `routes_reports.py:124,155`), the sort helpers `core.py:300 sort_default` / `core.py:305 sort_by`, the bespoke sorts (`routes_alloc.py:383` lots by `received_at`, `:411` ledger by `occurred_at`, `routes_ops.py:146` slots by `slot_index`, `routes_lists.py:371` + `cascade.py:61` entries by `sort_rank`, `cascade.py:72` entries-for-venue-wine, `routes_events.py:299` settlement originals, `calc.py:118` costing candidate lots), the `_seq` mint at `core.py:265-273`, `core.py:469 paginate` (verified it slices without re-sorting), the slot-closure write order at `routes_ops.py:193-215`, and investigation creation at `routes_reports.py:65-78` (at most one per run, so no intra-run tie).
- (c) Adjustment: wrote the claim about "records"/collection rows rather than about all ordered computations, so it does not silently restate the §3.7/§3.9 costing-candidate ordering (which uses the same `_seq` fallback but is described separately at PRD 269/303). Also dropped a first draft's "the append order stated in Section 3" as a universal, replacing it with the single verified §3.7 slot-closure example, since the PRD does not state an append order for every multi-entry operation.

**Edit 2 — §3.3 receipt guard order**
- (a) Subject: relative precedence of `ERR_DISTRIBUTOR_COMPLIANCE_HOLD` and `ERR_OFFER_COMPLIANCE_BLOCKED`, and whether §3.3's receipt list is an ordered list.
- (b) Paths enumerated: all four sites of either guard — `routes_alloc.py:62` (post offer, hold only), `:126-136` (file claim: duplicate → stale → not-open → hold → deadline → exceeds-offer, i.e. already §2.8-ordered), `:161` (award, block only), `:300-315` (receive: claim state → hold → block → `_receipt_checks`) — plus `_receipt_checks` at `:259-267` (future → venue → zone → capacity) and the direct-purchase path `create_lot()` at `:335-362`, which calls only `_receipt_checks` and so needs no compliance clause (PRD line 203 already lists exactly those four, in that order). Error-code HTTP mapping cross-checked at `core.py:107-108`.
- (c) Adjustment: scoped "this list is in evaluation order" to the receipt sentence only. I deliberately did not add an equivalent clause to §3.3's claim-filing sentence (line 191), whose prose order is *not* the impl order and which §2.8 already resolves — asserting order there would have created a new mismatch. Verified the receipt list's post-swap order maps monotonically onto §2.8 rungs 16, 18, 18, 19, 20, 20, 21, so the "matching the ladder of Section 2.8" phrase is true of every listed guard, not just the swapped pair. Left the pre-existing "Six checks" miscount (seven are listed) untouched, as it is outside Step 7 scope.

## Step 9 execution plan — 2026-09-04T01:47:00.000Z

Orchestrator decision (recorded per the AUTONOMY directive, no user available to consult): Step 9 will be run as **three sequential file-partitioned passes** over `implementation/` rather than as one single-shot full scan. Rationale: a 10-module / ~3,600-line implementation reliably under-covers in a single subagent pass — the known failure signature is a `PRD_COMPLETED.md` that comes back byte-identical to its source, meaning the exhaustive walk never actually happened. Partitioning bounds each pass's reading load and makes coverage auditable per module group. Each pass edits the same `PRD_COMPLETED.md` in place and runs strictly after the previous one, so later passes see earlier passes' edits and cannot conflict.

- Pass 1: `core.py`, `calc.py`, `cascade.py` (envelope, clock, validation ladder, pagination, all 14 calculations, cascades)
- Pass 2: `routes_master.py`, `routes_alloc.py`, `routes_lists.py`
- Pass 3: `routes_ops.py`, `routes_events.py`, `routes_reports.py`, `app.py`, `start.sh`

Orchestrator will verify after the final pass that `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` and ends at a real section boundary.

## Step 9: Complete PRD — 2026-09-04T02:22:00.000Z

Run as three sequential file-partitioned passes over `implementation/`, each editing the same `PRD_COMPLETED.md` in place. Combined: **78 edits — 49 ambiguity-pins, 28 mismatch-revisions, 1 internal cross-reference fix.** `PRD_FINALIZED.md` 104,283 chars → `PRD_COMPLETED.md` 127,331 chars (**+23,048**, +22.1%); 481 → 482 lines; heading set byte-identical to `PRD_FINALIZED.md` (no sections added, removed or reordered).

### Pass 1 — `core.py`, `calc.py`, `cascade.py` (17 patches: 14 ambiguity, 3 mismatch)
104,283 → 112,060 chars (+7,743).

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `core.py:311-316`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the real **wall clock**, the one instant not from the logical clock — `core.py:317`
- §2.3 — insert — ambiguity — non-integer `limit` is also `ERR_INVALID_PAGINATION`, and `limit` is examined before `offset` — `core.py:447-466`
- §2.3 — insert — ambiguity — boolean query params accept `true`/`1`/`yes` case-insensitively, everything else is false, never an error — `core.py:482-486`
- §2.4 — insert — ambiguity — client instants accept `Z`, an explicit offset, or no zone (read as UTC); truncated not rounded to ms — `core.py:200-216`
- §2.8 step 8 — insert — ambiguity — absent body = `{}`; non-object/unparseable body = `ERR_INVALID_REQUEST`; explicit `null` counts as absent; int rejects float+bool; malformed timestamp is 400 not 422; each of the 3 passes completes over all fields, fields examined in declared order — `core.py:387-431`
- §2.8 step 10 — revise — ambiguity — declared **string-length** bounds report `ERR_VALUE_OUT_OF_RANGE` (422), not `ERR_INVALID_REQUEST` — `core.py:441-444`
- §2.9 — insert — ambiguity — a recompute landing on unchanged derived values is not a mutation (no `version` bump); at most one increment per resource per operation; direct stamps are exempt — `cascade.py:20-39,98-122,205-238`, `core.py:276-281`
- §3.3 — insert — ambiguity — the under-subscribed branch still persists `raw_share` by the same `pool×requested÷demand` ratio (may exceed the request) and leaves `remainder_awarded` false — `calc.py:222-226`
- §3.3 — revise — **mismatch** — `list_entry_id` is set on all three slot-closure bucket entries **and** on every event-settlement/void entry; write-off entries leave it null — `cascade.py:168-202`, `routes_events.py:256`
- §3.4 — revise — **mismatch** — PRD claimed contest-score recomputation on every ledger entry naming the listing; impl recomputes only on entry create, on patch, and on slot closure — `cascade.py:228-238`, `routes_ops.py:233`
- §3.6 — insert — ambiguity — only the `PUBLISHED → REPRINT_PENDING` transition marks pinned events; a version already `REPRINT_PENDING`, or already `reprint_required`, only raises `stale_entry_count` — `cascade.py:265-287`
- §3.7 — revise — **mismatch** — under `WEIGHTED_AVERAGE` a pinned draw blends over the nominated lot **alone**, so it equals that lot's `unit_cost_cents` and the two methods agree; only an event settlement blends across several lots — `calc.py:162-168`, `routes_events.py:229-245`
- §3.8 — insert — ambiguity — a `PRESERVATION_EXPIRY`/`TEMPERATURE` approval that empties a lot moves it `ON_HAND → WRITTEN_OFF` directly; `DEPLETED` is never observable — `cascade.py:257-262`
- §3.9 — insert — ambiguity — a pour yield of zero or less fails with `ERR_VALUE_OUT_OF_RANGE` (422), on settlement as on pricing — `calc.py:302-309`
- §3.10 — insert — ambiguity — par report reads the **earliest-created** live version when a venue owns several lists each with one; empty `lines` with both counts 0 when none — `cascade.py:75-79`
- §3.10 — insert — ambiguity — `deficit_bottles` is reported signed (negative when over par); only `reorder_bottles` is floored at 0 — `calc.py:457-462`
- §3.10 — insert — ambiguity — sort tie beyond `sort_rank` settled by the version's entry order; `line_count`/`urgent_line_count` counted post-filter/pre-paging; `response_type` is `object` yet `meta` carries the four pagination fields — `calc.py:477`, `core.py:469-479`

Coverage: every function in all three modules read. Verified with no change needed: the complete `ERROR_STATUS` → §5 table (all 71 ids and statuses match exactly), markup bands, bottle/glass price chains, price bands, preservation table + 720h cap, FIFO draw order, `btg_close_split` drift absorption, contest-point formula and clamp order, over-subscribed waterfall ordering and cap loop, claim state mapping, all six event-pricing steps, `event_bottles_needed`, corkage quote, half-open pour-cost window, posture boundaries, par reorder case-rounding.

Left unpinned: `weighted_average_unit_cents` zero-availability return and the waterfall cap/redistribution loop (both unreachable given the declared minimums); `Decimal → float` JSON serialization (not observable under numeric comparison); `SALE_BOTTLE` has no writer anywhere and remains only a valid `reason` value, which is what the PRD already says.

### Pass 2 — `routes_master.py`, `routes_alloc.py`, `routes_lists.py` (34 patches: 21 ambiguity, 13 mismatch)
112,060 → 118,822 chars (+6,762).

- §2.1 — insert — ambiguity — venue-scope guards writes only; every single-resource read and collection listing is unscoped and unfiltered by venue, par report excepted — `routes_master.py:102/163`, `routes_alloc.py:87`, `routes_lists.py:77`
- §2.8 step 4 — insert — mismatch — where the venue is only reachable through the path record, that record resolves *first* and 404s before the scope check — `routes_lists.py:98`
- §2.8 step 10 — revise — mismatch — the 500-char `note` bound excepts the compliance review and request-changes notes (unbounded, empty allowed) — `routes_master.py:226`, `routes_lists.py:166`
- §3.1 — insert — ambiguity — key-set test precedes the target object's values and `venue_code` uniqueness; a non-numeric target value is `ERR_INVALID_REQUEST`, discovered after all declared field ranges — `routes_master.py:62`
- §3.1 — insert — ambiguity — unknown `byo_prohibited_categories` element → `ERR_INVALID_ENUM_VALUE`, checked before the target object; stored verbatim incl. duplicates — `routes_master.py:57`
- §3.2 — insert — ambiguity — omitted/null note overwrites `last_review_note` with null; a review always bumps the distributor's `version` even when restating the standing — `routes_master.py:239`
- §3.2 — insert — ambiguity — an already-passed `response_deadline` is accepted at offer creation — `routes_alloc.py:71`
- §3.3 — insert — ambiguity — claim guards run in §2.8 ladder order: duplicate → stale version → fulfilment state → hold → deadline → pool — `routes_alloc.py:121`
- §3.3 — insert — ambiguity — awarding never runs the closure test (an all-`REJECTED` offer stays `ALLOCATED`) and never consults the deadline — `routes_alloc.py:155`
- §3.3 — insert — ambiguity — `raw_share`/`remainder_awarded` survive a withdrawal — `routes_alloc.py:234`
- §3.3 — revise — mismatch — "Six checks" → "Seven checks" (the list has seven) — `routes_alloc.py:300`
- §3.3 — insert — ambiguity — receipt's availability recompute spans versions in *any* state, both directions (unlike §3.8's live-only cascade) — `routes_alloc.py:329`, `cascade.py:125`
- §3.3 — insert — ambiguity — direct lot is restock-only direction, any version state — `routes_alloc.py:362`
- §3.4 — revise — mismatch — at-most-one-live is an expectation, not enforced: publishing without `supersedes_version_id` leaves two live versions and overwrites `published_version_no` — `routes_lists.py:205`
- §3.4 — insert — ambiguity — cross-list `supersedes_version_id` → `ERR_LIST_VERSION_NOT_FOUND`; the named version's state is unchecked — `routes_lists.py:101`
- §3.4 — insert — ambiguity — `tasting_note` is null when absent — `routes_lists.py:334`
- §3.4 — insert — ambiguity — entry creation never re-derives `reprint_required` — `routes_lists.py:348`
- §3.4 — insert — mismatch — `pour_size_ml` is *not* nulled when `by_the_glass` goes false (and can be set while false); pour-size check precedes the draft-state check — `routes_lists.py:415,399`
- §3.4 — insert — ambiguity — a patch always mutates (version +1) even when it changes nothing, never re-applies the band gate, never re-derives availability/staleness, never touches the version record — `routes_lists.py:425`
- §3.5 — revise — ambiguity — request-changes' mandatory note is validated but persisted nowhere — `routes_lists.py:166`
- §3.5 — insert — ambiguity — a non-live `supersedes` target is silently ignored; publication leaves `stale_entry_count`/`reprint_required` alone, so a version published with the flag already true never reaches `REPRINT_PENDING` — `routes_lists.py:225`
- §4 table, 13 rows — revise/insert — mismatch (8) / ambiguity (5) — removed filters and fields that do not exist (venue "licence standing"/"licence state", bin "temperature class", wine "distributor and vintage", offer "allocation method", wine-list "service context", list-version "venue") and completed the filter sets actually implemented (distributor tier, offer compliance state, lot source claim, ledger listing/slot/event/write-off, entry price band + BTG flag) — `routes_master.py:106-341`, `routes_alloc.py:91-413`, `routes_lists.py:81-373`

Coverage: all 37 handlers read (11 master, 12 alloc, 14 lists). Both pass-1 deferrals that landed in this partition are resolved (`refresh_availability` call-site arguments pinned for the claim receipt and the direct lot; the later-patched-entry case pinned as the patch paragraph's frozen `bottle_price_cents`/`price_band`).

Left unpinned: collection filter values are never existence- or enum-validated (unknown values simply match nothing); unknown/extra body fields ignored by `validate_body`; Decimal fields serializing as JSON floats — all three are pass-1 core territory. `submit`/`allocate`/`archive`/`withdraw` ignore any request body (never call `get_body`), already covered by §2.8 step 8's "no body = empty object".

### Pass 3 — `routes_ops.py`, `routes_events.py`, `routes_reports.py`, `app.py`, `start.sh` (27 edits: 14 ambiguity, 12 mismatch, 1 cross-reference)
118,822 → 127,331 chars (+8,509).

- §2.2 — insert — ambiguity — envelope-level failures all report `ERR_INVALID_REQUEST` (404 unrouted, 405 wrong method, 500 unhandled), and trailing slashes are optional — `app.py:21,35-51`
- §2.4 — revise — ambiguity — clock may be wound backwards; 204 carries no body at all (Werkzeug drops it) — `routes_reports.py:264-265`
- §3.7 — insert — ambiguity — effective open-guard order interleaves rail occupancy between the lot-state and wine-agreement checks — `routes_ops.py:77-99`
- §3.7 — insert — ambiguity — both close pour counts floor at 0 (`ERR_VALUE_OUT_OF_RANGE`); absent/null `staff_education_pours` is written as 0 — `routes_ops.py:151-168`
- §3.7 — insert — ambiguity — **[pass-1 deferral 2]** a null `glass_price_cents` reads as 0 and yields no revenue rather than failing the close — `routes_ops.py:191`
- §3.7 — revise — mismatch — the bin recomputes on *every* `CLOSED` closure, not only a depleting one — `routes_ops.py:227`
- §3.8 — revise — mismatch — proposal guard order is lot state → venue agreement → bottle count, not the narrated order — `routes_ops.py:272-284`
- §3.8 — revise — ambiguity — approval entry carries `pours` 0 and null `list_entry_id`/`btg_slot_id`/`event_id` — `routes_ops.py:344-347`
- §3.8 — revise — ambiguity — reversal entry carries `pours` 0 and the same null joins — `routes_ops.py:410-413`
- §3.8 — revise — ambiguity — **[pass-1 deferral 1]** the reversal's availability cascade runs unconditionally, lifts only `OUT_OF_STOCK` entries, and only on `PUBLISHED`/`REPRINT_PENDING` versions — `routes_ops.py:430`
- §3.9 — revise — ambiguity — error ids for plan length, malformed line shape, and `pours_per_seat` above 6 vs. the membership-classed floor of 1 — `routes_events.py:99-110`
- §3.9 — insert — ambiguity — the pinned version need not belong to the event's venue; two lines may name one listing — `routes_events.py:85-96,127`
- §3.9 — revise — ambiguity — `settled_cogs_cents`/`settled_revenue_cents` null at creation; `pour_plan` normalised to its two fields, extra keys discarded — `routes_events.py:137-151`
- §3.9 — revise — mismatch — `REPRINT_PENDING` is settleable in its own right; only the stale flag blocks; archive is unreachable for a pinned version — `routes_events.py:217-223`
- §3.9 — revise — mismatch — one entry per *(line, lot)* draw (not per lot), `pours` 0, naming `list_entry_id` and `event_id`, in plan-then-`received_at` order; no contest-point recompute — `routes_events.py:250-258`
- §3.9 — revise — ambiguity — void gathers originals by `event_id`/`EVENT` in `created_at` order, negates `pours` too, and runs the live-only restock availability cascade — `routes_events.py:293-321`
- §3.9 — insert — ambiguity — cancel's `note` is validated but persisted nowhere — `routes_events.py:337`
- §3.10 — insert — ambiguity — pour-cost report's period params are mandatory query params; absent or unparseable is `ERR_INVALID_REQUEST` — `routes_reports.py:86-93`
- §3.10 — revise — mismatch — corkage checks prohibited category *before* the bottle limit; bad `byo_categories` element is `ERR_INVALID_ENUM_VALUE`; numeric floors — `routes_reports.py:216-240`
- §4 preamble — revise — mismatch — clock returns 204 with no body, not "an empty data object" — `routes_reports.py:265`
- §4 (write-off list) — revise — mismatch — filters are venue/lot/**btg slot**/state; there is no reason filter — `routes_ops.py:315`
- §4 (event list) — revise — mismatch — filters include `list_version_id` — `routes_events.py:167`
- §4 (price) — revise — mismatch — no "food cost"; no request body — `routes_events.py:176-177`
- §4 (confirm) — revise — mismatch — pins the list version, not the seat count; no body — `routes_events.py:192-207`
- §4 (settle) — revise — mismatch — settles on the planned `seat_count`; there is no attended count and no body — `routes_events.py:211-226`
- §5 preamble — revise — mismatch — `ERR_INVALID_REQUEST` is the one identifier that also carries 404/405/500 — `app.py:39-51`
- §3.1 — revise — coherence — corkage cross-reference "Section 3.9" → "Section 3.10"

Coverage: all 27 handlers in the partition read (10 ops, 8 events, 9 reports) plus `app.py` and `start.sh` in full. Route count reconciles: 69 `@bp` routes in `implementation/` vs. 69 rows in the §4 table.

Left unpinned: `app.py`'s bind (`0.0.0.0`, `PORT` defaulting to 10000, threaded) and `start.sh`'s conditional `pip install` — deployment mechanics with no API surface, and pinning them would require a new section; `app.json.sort_keys = False` (JSON key order carries no semantics); `close_slot` not re-examining the lot's state (§3.7 enumerating exactly two close preconditions already excludes a third, and the state is practically unreachable); the defensive "version row missing" branch in `create_slot` (unreachable).

**Whole-document coherence check (pass 3): PASS.** Ends at a real boundary (completed §5 error table, last row `ERR_NO_REVENUE_IN_PERIOD | 422`); byte-different from `PRD_FINALIZED.md`; a sentence-level duplicate scan over all prose >60 chars found 0 repeated sentences; both tables structurally intact (69 endpoint rows, 71 error rows). Two cross-pass contradictions were resolved: §2.4's "204 with no body" vs §4's "204 with an empty data object" (impl confirmed empty), and the §3.1 corkage cross-reference. The restock-cascade statements now read consistently across §3.7/§3.8/§3.9 (live-only) and §3.3 (any version state for a direct receipt), matching `refresh_availability`'s three distinct call sites.

### Orchestrator final verification — 2026-09-04T02:23:00.000Z

- `PRD_COMPLETED.md` exists, 482 lines / 127,331 bytes; `cmp` against `PRD_FINALIZED.md` confirms it is NOT byte-identical (the known "scan never ran" signature is absent).
- Heading set diffed against `PRD_FINALIZED.md`: **identical** — 28 headings, no sections added, removed or reordered, exactly as the no-new-sections constraint requires.
- `tail` confirms the document ends on the final row of the §5 error table — no truncation.
- All 10 `implementation/*.py` mtimes (latest 01:23) predate all 8 `results.$i.json` mtimes (01:31), so the verified 8×254/254 green sweep reflects the final implementation byte-for-byte. Steps 8 and 9 edited only PRD markdown and touched no code, so no re-sweep was required.

**Pipeline complete.**
