# Worklog — task_0927_home_inventory_valuables

Scenario (verbatim): `927. Home Inventory & Valuables Cataloging Service: room-by-room inventory & photo/serial, valuation & appraisal linkage, insurance-documentation package, cloud vault & update, post-loss claim support, estate/downsizing use, subscription/refresh, secure sharing`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-08T12:23:30.000Z

Created `tasks/task_0927_home_inventory_valuables/` and `tasks/task_0927_home_inventory_valuables/workspace/`. Index 0927 follows the `task_0926_anchor` placeholder in `./tasks/`.

## Step 2: Generate scaffold — 2026-08-08T13:33:00.000Z

All three artifacts are written and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables/SCAFFOLD.yaml` (3,783 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,948 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables/SCAFFOLD_CORNER_DESIGN.yaml` (3,475 lines)

## Density metrics
| Dimension | Target | Delivered |
|---|---|---|
| Entities | 14–16 | **17** |
| Endpoints | 60–72 | **78** (`api_prefix: /vault` + `/_clock/set_current_utc`) |
| Error codes | 26–36 | **42** |
| Dual-variant calculations | 5+ | **5** of 15 total calcs |
| State-machine axes | 9+, ≥5 non-linear | **11 axes, 11 non-linear** (2 parallel dims on Subscription, 2 on Item, 4 cyclic, 3 branching, 1 posture-driven) |
| Validation ladder | 20+ rungs | **38 validations = 38 rungs**, strictly ordered, one rung per number |
| OCC rules | 3+ | **4** (Policy, Subscription, Household, EstatePlan) |
| Conservation invariants | 3+ | **3** (policy allowance cents; frozen-item record count; estate allocation units) |
| Max cascade depth | 5 | **5** (Appraisal VOIDED → Item revaluation → Policy totals → Package EXPIRED → ClaimLine settlement_hold); plus three depth-4 chains |
| Declared constants | all valued | **75** (27 top-level scalars + 24 tier-table values + 24 per-calculation) — zero undeclared |
| Roles | — | 8, `role_model: segregation_of_duties` (2 SoD rules at rung 16) |

§1.8: 9 rule_ids × 2 = **18 instances**. §1.9: **9 sections, 61 instances** (48 executable + 13 `excluded_because` stubs, all refs resolving).

## Verification
- `yaml.safe_load` clean on all three files (needed fixes: `field?` tokens and `$.data[0].x` / `errors[...]` inside flow collections had to be quoted).
- `scaffold_lint.py` → **`VERDICT: clean lint`** — 881 calls scanned, all conform to §1.5; all 17 entities' FKs reverse-reachable.
- Independent checks: 0 unresolvable `grounds` refs across both design files; 79 instance names unique; no forbidden concurrency vocabulary; every worked number recomputed in Python (ACV 353333/366667/373333, per-line rounding 569973 vs 569972, deductible split 80000/20000, coverage gap 100000 vs 300000, proration 3334 vs 5000, fair-division spread 5.00 vs 5.15).

## Reachability repairs (audit clause d)
1. **Graph** — Appraisal-void cascade hops 3/4 were conditioned on the item being SCHEDULED and on `coverage_gap_cents` actually changing; in the depth-5 fixture the gap goes 0→0, so hops 4–5 were unreachable. Made both hops unconditional on hop 3 having executed.
2. **Graph** — `Item.evidence_tier PHOTO_SERIAL→PHOTO_ONLY` cascade hop 3 needs a PENDING ClaimLine on the item, but rung 12 blocks asset deletion on frozen items. Documented on `POST /vault/claims/{claim_id}/lines` that a claimed item need not sit in `affected_room_ids`, so a claimed-but-unfrozen item exists.
3. **Graph** — a single-line claim auto-transitions UNDER_REVIEW→DENIED, making `DENIED→APPEALED` unreachable. Rebuilt the bounded-cycle instance on a two-line claim (one approved).
4. **Graph** — `Member.status = REMOVED` had no producing transition (enum closure). Dropped the field and its list filter.
5. **Graph** — `Appraiser.status = SUSPENDED` had no producer. Added `POST /vault/appraisers/{appraiser_id}/suspend`, which also yields a cross-entity guard on certify.
6. **Graph** — `Asset.item_id` had no reverse-reachability GET (the sub-resource path used `{item_id}`, not `{id}`). Replaced with `GET /vault/assets/{asset_id}` + `GET /vault/assets?item_id=`.
7. **Graph** — `Item.allocated_quantity` summed across all plans, so two live EstatePlans double-counted. Scoped it to `{DRAFT, PROPOSED, APPROVED}` and added a one-live-plan-per-household rule at rung 14.
8. **Graph** — GROSS vs NET fair division was unobservable (`valuation_mode` was create-only). Added `valuation_mode?` to propose and a `PROPOSED→PROPOSED` re-proposal self-loop.
9. **Graph (determinism)** — the frozen logical clock makes rows share `created_at` to the millisecond, leaving every `created_at ASC` ordering ambiguous. Added a top-level `ordering_contract` pinning creation order as the universal tie-break (never `id`).
10. **Graph** — `ShareGrant.voided_reason = SCOPE_DELETED` had no producer; wired it to the claim-withdraw cascade for CLAIM-scoped grants.
11. **Arithmetic** — `ERR_QUOTA_EXCEEDED` / `ERR_DOWNGRADE_BLOCKED_BY_USAGE` were only hittable via 51 item creations. Retuned the tier byte quotas (BASIC 2 GB, PLUS 20 GB) so one oversized asset upload hits both rungs.
12. **Arithmetic** — the §1.8 ACV fixture jumped the clock to 2026-12-01, past `PACKAGE_VALIDITY_DAYS` (180) from the 2026-05-01 snapshot, so hook H1 would have EXPIRED the package and the claim creation would have failed at rung 14. Moved the jump to 2026-08-01 and recomputed the asserted ACV (353333) and divergence (13334).
13. **Arithmetic** — the first coverage-gap A/B design was order-symmetric (both variants gave the same gap). Retuned to a scheduled-first item whose blanket draw starves its own allowance, yielding 100000 vs 300000.
14. **Housekeeping** — `SCHEDULE_REQUIRED_THRESHOLD_CENTS` was declared but referenced by nothing; gave it an observable use as `schedule_required_unscheduled_count` on the coverage-gap read.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean; 17 entities / 78 endpoints / 42 error codes / 11 state machines / 15 calculations / 38 validations confirmed by direct parse. Independent ALL_CAPS sweep: 0 constant-shaped tokens (`*_LIMIT|_THRESHOLD|_WINDOW|_DAYS|_MAX|_MIN|_RATE|_FEE|_CAP|_QUOTA|_BYTES|_CENTS|...`) lacking a declared value; 57 residual ALL_CAPS tokens all English prose words or enum members; `RESTRICTED_GATE_BLOCK_LIST` confirmed valued at `global_constants` line 120.

## Step 3: Copy shared files — 2026-08-08T13:35:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0927_home_inventory_valuables/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-08T13:53:00.000Z

The PRD is complete and verified on disk. Final state: **631 lines, 18,081 words** at `/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables/workspace/PRD.md`, ending at §5 with no audit footer.

## Rendered vs. scaffolded

| Element | Scaffold | PRD | Status |
|---|---|---|---|
| Endpoints | 78 | 78 | complete |
| Error codes | 42 | 42 (all 42 also named in §2/§3 prose, not just the §5 table) | complete |
| Ladder rungs | 38 | 38, numbered 1–38 | complete |
| State-machine axes | 11 | 11 (64 transitions, **all 64** carry explicit `FROM → TO` notation) | complete |
| Calculations | 15 | 15 (5 with variants: ACV ×3, coverage-gap ×2, deductible ×2, fair-division ×2, proration ×2) | complete |
| Entities | 17 | 17 (14 full common-fields, 3 with only `id`/`created_at`) | complete |
| Constants | 53 distinct name/value pairs checked (incl. all 24 tier-table values) | all present with values | complete |
| Conservation invariants | 3 | 3 (§2.12) | complete |
| OCC rules | 4 | 4 (§2.10, plus rung 38) | complete |

Nothing was dropped — no scaffold element went unrendered.

## Hard contracts

```
Field coverage check:
- entities[].fields: 146 required, 146 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 35 required, 35 present, 0 missing
- endpoints[].path_params: 17 required, 17 present, 0 missing
- endpoints[].output (computed reads): 20 required, 20 present, 0 missing
- concurrency_rules[].occ_field: 4 required, 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed as an ordered ladder, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed with preconditions and side effects, 0 missing
- calculations[]: 15 checked, 15 fully expressed (formula, constants, precision, rounding order), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 checked, expressed, 0 missing
- entities[].fields[] structured content: 146 checked, reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (subscription outcomes, refresh bands, 4 evidence upgrades / 3 downgrades, 4 share-grant terminals, 3 claim-withdraw paths, 2 coverage-gap variants, 2 deductible modes, 2 proration modes, 2 fair-division modes), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1197
- tokens starting with `/`: 0   (also 0 unbackticked `/vault` mentions)
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## How the eight emphases were handled

1. **Version-bump ledger** — §2.9 is a 45-row per-operation table naming every row whose `version` moves, prefaced by the one-bump rule in §2.4 (one increment per row per request regardless of touches; created rows enter at 1; a counter recomputed to its existing value does not bump).
2. **Timestamps** — §2.5 gives five numbered rules: server-written instants always three fractional digits (with the full field list), derived instants inherit that, caller-supplied instants echoed byte-for-byte (full field list), `current_utc` reproduces `to_iso8601` verbatim, and all comparisons are semantic.
3. **Closed enum routing** — rung 4 lists all 20 fields that route to `ERR_INVALID_ENUM` and states "no other field routes here"; §2.3 separately pins that off-enum *list filters* yield an empty page, with the coverage-gap `basis` as the single 422 exception.
4. **Ladder normative and total** — first-firing rung wins; §2.7 + rungs 10/11/12 state exactly which rungs each gate pre-empts and the full write-gate exclusion list (13 entries) and restricted block list (2 entries).
5. **Ordering** — §2.3 states `created_at` ASC with a creation-order tie-break that is never `id`, and propagates it to all four ordered computations.
6. **Projections** — §2.11 enumerates the serialized field set for all 17 entities plus the 2 computed reads, states list and detail are identical, names formula intermediates that are nonetheless present (`acv_value_cents`, `gross_value_cents`, `capped_value_cents`, `useful_life_months`), and gives the role redaction matrix.
7. **Cascades incl. non-firing legs** — six cascades rendered hop-by-hop (lapse ×4, evidence downgrade ×4, certify ×4, void ×5, generate ×4, execute ×4), each naming its skipped legs (partial-redaction grants not voided by lapse; non-`PENDING` claim lines untouched; `GENERATED`/`DRAFT` predecessors not superseded; partly-kept items not disposed). §2 carries no competing cascade summary, so no summary/detail drift is possible.
8. **Constants** — all 53 distinct name/value pairs verified present by grep against the finished document, including the full 3×8 tier table.

Two judgement calls worth flagging: (a) package expiry is rendered as one unified rule — either leg puts pending claim lines on settlement hold *and* voids scoped `ACTIVE` grants — reconciling the scaffold's asymmetric `GENERATED→EXPIRED` / `DELIVERED→EXPIRED` side-effect lists with the `settlement_hold` field definition; (b) the clock advance bumps versions only on rows a reposture step actually changed, with in-place valuation refreshes (e.g. `acv_value_cents`) explicitly stated as non-bumping.

**Orchestrator independent verification:** PRD confirmed 631 lines / 18,081 words on disk, §1–§5 all present, file ends at the §5 error table. Independent endpoint diff (§4 table parsed, path params normalized) vs scaffold `endpoints[]` → **78/78, 0 missing, 0 extra**. Independent `ERR_*` token diff vs scaffold error catalogue → **42/42, 0 missing, 0 extra**.

## Step 5: Generate unit tests — 2026-08-08T14:25:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message. Step 5 returned first, ~4 min ahead of Step 6 — so `workspace/implementation/` was partially on disk during test-gen's final stretch. Containment verified by the orchestrator below.)

Test infrastructure and suite are complete.

## Files written

**`test_helpers/`** (2,524 lines): `__init__.py` 39 · `api_client.py` 401 (one method per PRD §4 endpoint) · `api_errors.py` 98 (42 error ids + status map, registered with the framework) · `assertions.py` 549 (incl. `parse_instant` / `assert_same_instant` / `assert_three_digit_utc`, per-entity assertions, three conservation-invariant checkers) · `constants.py` 95 · `factories.py` 199 · `fixtures.py` 532 (7 tiers of composite setup) · `test_users.py` 66 (per-instance builders for all four entity-backed roles + `NO_AUTH_HEADERS`) · `types.py` 545.

**`test_suite/`** (4,816 lines): `conftest.py` + 15 test files, `test_01`–`test_06` for queue B, `test_07`–`test_15` for queue A.

## Coverage

- **Queue A (Difficulty)**: 18/18 instances translated, **2 tests each = 36 tests**. Zero skipped.
- **Queue B (Corner)**: **47/48** non-stub instances translated, 1 test each. All 13 `excluded_because` stubs verified to cross-reference a real difficulty instance; none translated.
  - **Skipped: `Corner/entities/system_and_computed_fields_on_item_ignore_client_supplied_values`** — it asserts that `POST /vault/items` carrying `lifecycle_state` / `declared_value_cents` returns `ERR_INVALID_REQUEST`. The PRD nowhere says unknown/extra body fields are rejected; rung 3 covers only missing fields, type mismatches, empty required arrays and unparseable datetimes. Two faithful PRD-only implementers would split on ignore-vs-reject, so unique derivability fails.
- **Totals: 83 `def test_` / 83 `Design:` tags** (verified programmatically against both YAMLs).

## Deviations applied

1. **`Difficulty/cross_entity_state_dependency/item_asset_upload_gated_by_subscription_status_but_claim_intake_is_not`** — item created *with* `serial_number: "GN-M1"` (recipe had none). Without a serial the RECEIPT upload lands on `PHOTO_ONLY`, not the asserted `DOCUMENTED`. Claim unchanged.
2. **`Corner/calculations/effective_value_precedence_appraisal_then_acv_then_declared`** — inserted `set_clock("2026-05-10T00:00:00Z")` before certify; the recipe certifies while the clock still precedes `inspection_end_at`, which the PRD refuses. Age in whole 30-day months is unchanged (4), so all asserted values hold — including `valid_until_at == 2029-05-09T00:00:00.000Z`, which only reconciles under this instant.
3. **`Corner/cross_cutting_complexity_layers/soft_deleted_asset_is_excluded_from_the_default_asset_list`** — the two asset states are separated with explicit `status=STORED` / `status=DELETED` filters. The PRD never says the unfiltered list hides deleted rows and explicitly keeps them "readable"; the soft-delete claim itself is fully asserted.

Two assertions were **dropped** as PRD-contradicting (noted in their docstrings, claims otherwise intact): the successor item's `evidence_tier == PHOTO_SERIAL` in `item_replace_moves_predecessor_to_replaced_and_frees_its_serial` (a fresh row owns no PHOTO → tier is `NONE`), and the default-asset-list row count above.

One assertion uses `validate_error_is_one_of` — the executor-self-approval leg of `propose_with_unallocated_items_and_approve_by_the_executor_are_both_refused`. §2.1's rung-8 clause ("Operations reserved to the homeowner additionally require `member_role` to be `OWNER`") never enumerates those operations, so `ERR_SEGREGATION_OF_DUTIES` and `ERR_HOUSEHOLD_SCOPE_VIOLATION` are both faithful readings; both are accepted, and the 403 + plan-stays-PROPOSED outcome is still pinned.

## Self-audit

- Every `def test_` has exactly one `Design:` line, and it is the last docstring line — 83 = 83.
- Every tag resolves to a real non-stub instance (verified against both YAMLs via `yaml.safe_load`); zero stub-tagged tests; all 13 stub cross-references resolve.
- **165 PRD citations verified verbatim** against `PRD.md` (whitespace-normalized substring match), every one ≥8 words.
- Zero `pytest.mark.skip` / `xfail` / `skipif` / commented-out assertions anywhere.
- All 25 files `py_compile` cleanly; pyflakes reports no undefined names; `pytest --collect-only` collects 83 tests with no import errors.
- No import of, reference to, or path string touching `workspace/implementation/`; no scaffold terminology in emitted code.

## Step 6: Generate implementation — 2026-08-08T14:29:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables/workspace/implementation/`.

## Scale
**24 Python modules + `start.sh` + `requirements.txt`, 5,556 lines.** Layout: `app.py`, `registry.py`, `ladder.py`, `store.py`, `derive.py`, `cascades.py`, `calc.py`, `money.py`, `timeutil.py`, `serializers.py`, `envelope.py`, `errors.py`, `constants.py`, and `routes/` (12 modules).

## Completeness gate
`TOTAL 78 / LIVE 78 / MISSING [] / EXTRA []` — scaffold `endpoints[]` diffed programmatically against a live in-process `app.url_map`, path-parameter names normalized to `{}` on both sides. I also verified every `WRITE_GATE_EXCLUSION_LIST` (11) and `RESTRICTED_GATE_BLOCK_LIST` (2) entry resolves to a registered `(method, template)` — zero orphans.

## Timestamp-rendering adjudication (bug #1)
Two funnels, no third path. `derive.stamp()` writes server instants; `derive.keep_raw()` stores caller strings verbatim plus a parsed datetime used only for comparison.

- **Always three fractional digits + `Z`** (`timeutil.render_server`, from the logical clock): `created_at`/`updated_at` on all 14 versioned entities and `created_at` on the three light ones (`Asset`, `CategorySchedule`, `PackageLine`); `period_start_at`, `period_end_at`, `past_due_since_at`, `last_attested_at`, `refresh_due_at`, `certified_at`, `generated_at`, `delivered_at`, `submitted_at`, `proposed_at`, `approved_at`, `executed_at`; plus `meta.api_request_timestamp`.
- **Derived instants inherit the three-digit style** because they go through the same funnel: `valid_until_at` = `certified_at` + 1095d, package `expires_at` = `generated_at` + 180d. A row created before any clock advance carries `2026-05-01T00:00:00.000Z`.
- **Reproduced byte-for-byte from the caller**: `acquired_at`, `captured_at`, `inspection_start_at`, `inspection_end_at`, `effective_from`, `loss_date`, ShareGrant `starts_at`/`expires_at`.
- **Clock endpoint**: `current_utc` echoes `to_iso8601` verbatim (verified over HTTP: input `2026-06-01T12:34:56Z` → `current_utc` identical, while the same request's `created_at` renders `2026-06-01T12:34:56.000Z`).
- All comparisons are semantic (aware `datetime`), never string.

## Enum-routing adjudication (bug #2)
One shared helper — ladder rung 4 in `ladder.py` — driven by three declarative maps (`enums`, `array_enums`, `query_enums`). **20 PRD field slots across 19 distinct names** (`category` appears twice: `Item.category` and `CategorySchedule.category`), covering 22 (field, endpoint) pairs; audited programmatically. Rung 3 explicitly **skips** enum-listed fields so a bad member value can never fall through to `ERR_INVALID_REQUEST`, and no other field is registered on rung 4 — every other validation failure (missing field, wrong JSON type, empty required array, unparseable datetime, the four malformed-payload cases, duplicate email, share scope-pointer mismatch, heir/disposition pairing) routes to `ERR_INVALID_REQUEST`.

## 38-rung ladder
One ordered evaluation in `ladder.run_ladder`. Rungs 1–11 and 38 are generic, computed from each endpoint's declaration; rungs 12–37 are per-endpoint closures registered under their rung number and executed by `for rung in range(12, 38)`, so the lowest-numbered violated rung always wins. All rungs 12–38 are implemented across the endpoint set. Hook H2 runs before rung 1 for every `/vault` request.

## OCC and conservation
4 OCC rules via one `occ=(field, error_id, parent_getter)` declaration evaluated at rung 38 — `expected_policy_version`/`ERR_STALE_POLICY_VERSION` (schedule), `expected_subscription_version` (change-tier), `expected_household_version` (generate), `expected_estate_plan_version` (allocation). 3 invariants: allowance cents maintained by explicit `+=`/`release_allowance()` of the exact amount the item consumed (round-trip verified lossless, including replacement/disposal releases); frozen-item count via `unfreeze_items_of_claim()` keyed on `frozen_by_claim_id` so a second claim's freeze survives; allocated units recomputed from allocations under live plans only (drops to 0 on EXECUTED).

## Self-audit
- `grep -rE "sqlite|json\.dump|pickle|/tmp|datetime\.now|utcnow|time\.time\(\)"` → **zero hits**. In-memory dicts only; no seeding anywhere.
- Booted via `bash start.sh` on `$PORT`/`0.0.0.0`, foreground with `exec`, guarded pip install; envelope shape confirmed over real HTTP for success, array+pagination, and error bodies.
- Four smoke suites (~200 assertions) covering ACV variants, per-line rounding (3 × 1798.5 → 5397, the pinned order), both waterfall variants, claim settlement with PRO_RATA anchor remainder (16364/13636) and settle-time re-run over the approved subset, appeal loop, evidence-downgrade cascade, depth-5 appraisal-void cascade, package supersede + grant voiding, refresh bands, all three posture gates, proration DAILY (−5600) vs WHOLE_PERIOD (2000), fair division GROSS/NET, share redaction and exhaustion: **0 failures**.

Two under-specified points I resolved without inventing errors, worth flagging: (a) the redemption envelope's `total_effective_value_cents` sums the displayed rows per scope kind (items' `effective_value_cents`; package lines' `snapshot_effective_value_cents`; claim lines' `net_settlement_cents`) — the PRD names the field but never defines its scope; (b) claim-line creation enforces no claim-status precondition, because §3.7 and the rung tables name none for that endpoint.

**Orchestrator independent verification of Steps 5/6:**
- `def test_` count **83** == `Design:` tag count **83**.
- Zero `pytest.mark.skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`.
- **Isolation-overlap containment (Step 5 finished before Step 6, so `implementation/` was on disk during test-gen's tail):** grep of the whole test tree for the string `implementation` and for imports of any impl module (`app`, `registry`, `store`, `derive`, `serializers`, `money`, `timeutil`, `calc`, `errors`) → **0 hits**. Word-level hits on `ladder` / `cascades` / `envelope` were inspected individually — all six are PRD vocabulary inside docstrings, none reference impl internals. No breach.
- All 25 test files `py_compile` clean; all 27 impl files present, 5,547 lines.
- Impl hygiene grep `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` → **0 hits**.
- **Independent route diff** — imported `workspace/implementation/app.py` in-process, enumerated `app.url_map`, normalized path params on both sides, diffed against scaffold `endpoints[]` → **78/78 live, 0 missing, 0 extra** (Flask's `/static` excluded).

## Step 7: Run tests and iterate — 2026-08-08T15:02:00.000Z

All clean. `implementation/` is byte-for-byte unchanged from what was generated.

## Result: 8/8 rounds green (83/83 each), two consecutive sweeps

**Iterations:** 6 sweeps. Final: rounds 1–8 all `83/83 passed, 0 failed, 0 errors`, reproduced twice back to back.

### Tests deleted
**None.** One test was split under STEP 1c (partial coverage), not deleted.

### Fix applied to `test_suite/`
`test_suite/test_03_valuation_calculations.py` — `test_actual_cash_value_never_falls_below_the_salvage_floor`. The only real assertion failure, deterministic across all 8 rounds of sweep 1 (`assert 'NONE' == 'ACV'`).

The test asserted `effective_value_basis == "ACV"` / `effective_value_cents == 40000` on the **201 create response**. PRD §3.3 states the opposite verbatim:

> "A new item lands in `lifecycle_state` `DRAFT` with `evidence_tier` `NONE`, `valuation_state` `UNVALUED`, `effective_value_cents` 0, `effective_value_basis` `NONE`, … ; its `acv_value_cents` is computed immediately against the current clock."

and §3.4's trigger list — "re-run whenever an item's assets, declared value, serial number or appraisals change, and at the end of every clock advance" — does not include item creation. The explicit carve-out singling out `acv_value_cents` as computed immediately implies the other valuation fields are not. The implementation is the faithful reading; the scaffold rule (`Corner/calculations/acv_bottoms_out_at_the_salvage_floor_for_a_fully_depreciated_item`) is itself internally inconsistent — it asserts `lifecycle_state == DRAFT` alongside `effective_value_basis == ACV`, and its own cited grounds (`calculations.item_actual_cash_value`, `salvage_floor_pct`, `acv_value_cents`) never mention `effective_value_*`. Classic **computed-field / verb widening beyond cited grounds**.

Kept the covered, uniquely-derivable assertions (`acv_value_cents == 40000` — the salvage-floor claim the test exists to pin — plus `lifecycle_state == "DRAFT"`); replaced the two uncovered ones with §3.3's verbatim creation defaults. No assertion was weakened, no skip/xfail added.

### Fixes to `test_helpers/` and `implementation/`
**None.** `implementation/` is byte-for-byte as generated (verified: no `_serve`/`make_server`/`SO_REUSEADDR` residue, imports unchanged, no wall-clock, no persistence, no seeding).

### Key finding: the "could not be restarted" noise was host saturation, not code
Sweeps 2–4 showed 1–7 setup ERRORs per round (`failed: 0` always), on **completely different tests each sweep** — zero overlap. I confirmed it was infrastructural (boot is ~0.45s; logs show no application output) and tried the known pre-bind + `make_server(fd=)` fix. **It made things strictly worse** and I reverted it: the 20s bind-retry loop outlives the runner's readiness probe, so a rejected respawn becomes a PPID-1 **orphan squatting the port**, feeding the next round's failures. Root cause was accumulating orphan `app.py` processes (5 found) plus two accidentally overlapping sweeps. Reaping orphans and letting load settle below 2 before a single sweep produced clean 8/8 twice. Worth knowing for future runs: **reap orphan servers between sweeps and never overlap two.**

### Isolation-overlap audit (Step 5 finished ~4 min before Step 6) — verdict: PASS
- **Timestamp assertions (11):** 5 semantic `assert_same_instant`, 3 null-checks, 1 structural (`"updated_at" not in line`, per §2.4 PackageLine), 1 `assert_three_digit_utc` on `created_at` — explicitly pinned by §2.5 rule 1 ("A row created before any clock advance therefore carries `created_at` of `2026-05-01T00:00:00.000Z`"). **Zero string-equality against a rendering.**
- **Positional assertions (4):** every one guarded by an immediately preceding `total_count == 1` / `len(rows) == 1`. Zero multi-row ordering assertions, zero `id`-order assumptions.
- **Exact-version assertions (1):** `item["version"] == 1`, tracing to §2.4 "starts at 1 when the row is created". All four OCC tests read versions live (`read_household_version`, `read_policy_version`, …) rather than hardcoding — **no assertion depends on §2.9's bump ledger.**
- **Response-field tokens (137 distinct):** 114 appear verbatim in PRD.md; the 23 that don't are all test-local `ctx` scenario keys (`owner_headers`, `executor_headers`, `item_one`, `line_a`, …), none an API response field.

No implementation-shaped assertions found — the green suite is not an artifact of the concurrent-generation overlap.

**Orchestrator independent verification of the green result:**
- All 8 `results.N.json` re-parsed independently → **83 individual rows each**, status distribution `{'passed': 83}` in every round, `failed=0 errors=0`; sorted test-name lists **byte-identical to round 1 in all 7 comparisons** (rules out a round silently collecting a smaller suite).
- `def test_` count **83** == `Design:` tag count **83**.
- `grep -rniE "skip|xfail"` over `test_suite/` + `test_helpers/` → **0 hits** (not even the English word in a docstring).
- Impl hygiene grep `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` → **0 hits**.
- `find implementation/ test_suite/ test_helpers/ -newer results.1.json` (excluding results/marker/pycache) → **empty**, so the green result describes the shipped tree.
- Each `round_logs/round.N.log` contains `Killed` **exactly once** — the expected per-test-isolation pre-boot server swap, not a crash.
- Orphan scan after the sweep → **0 residual `app.py` / `start.sh` processes**.

## Step 8: Finalize PRD — 2026-08-08T15:07:00.000Z

(Step 8 ran rather than being skipped: the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes, and Step 7 applied one `test_suite/` fix.)

## Result: zero edits — `PRD_FINALIZED.md` is byte-identical to `PRD.md`

- `workspace/PRD_FINALIZED.md` created (631 lines / 130,827 bytes, same md5 `fb551b69…` as `PRD.md`). **0.0% delta.**
- Changes: **none.**

### Why

`<step_7_diff>` contains exactly one fix — a `test_suite/` fix, no impl fixes, no test deletions, no `test_helpers/` fixes. I traced its subject (item-creation valuation fields) through the implementation and found PRD.md already determines every observable choice the implementation makes there.

**Subject:** what a newly created item row holds for `lifecycle_state`, `evidence_tier`, `valuation_state`, `effective_value_cents`, `effective_value_basis` and `acv_value_cents`, and whether the ACV computed at creation is surfaced.

**Impl paths enumerated** (grepped `refresh_item|new_item_row|acv_cents|acv_value_cents` across all of `implementation/`, then read each site):

- `implementation/routes/items.py:72-107` — `new_item_row`: writes the defaults literally (`lifecycle_state="DRAFT"`, `evidence_tier="NONE"`, `valuation_state="UNVALUED"`, `effective_value_cents=0`, `effective_value_basis="NONE"`, `coverage_mode="BLANKET"`, `scheduled_policy_id=None`, `scheduled_value_cents=0`, `declared_value_cents=0`, `declared_by_member_id=None`, `allocated_quantity=0`, `frozen_by_claim_id=None`) and then, and only then, `row["acv_value_cents"] = calc.acv_cents(row, clock.now)` at line 106. It never calls `derive.refresh_item`.
- `implementation/routes/items.py:155-173` (`create_item`) and `:465-490` (`replace_item`) — the only two callers of `new_item_row`; the replacement successor gets identical treatment, so no wording about creation would have needed widening.
- Every `derive.refresh_item` callsite — `routes/assets.py:84` (upload), `routes/assets.py:138` (delete), `routes/items.py:279` (patch), `routes/items.py:308` (declare-value), `routes/valuation.py:326` (certify), `routes/valuation.py:366` (void), `derive.py:427` (appraisal expiry), `derive.py:478` (clock advance). That set is exactly PRD §3.4's trigger list — "assets, declared value, serial number or appraisals change, and at the end of every clock advance" — and item creation is absent from both the code and the PRD list.
- `implementation/derive.py:272-292` — `refresh_item` is the only place `effective_value_*`/`valuation_state` move off the appraisal/ACV/declared precedence, confirming creation cannot reach them.
- `implementation/calc.py:31-58` — `acv_exact`/`acv_cents` implement §3.4's curve and return 0 when `purchase_price_cents` is null or no schedule exists.
- `implementation/serializers.py:42-67, 226-234` — `acv_value_cents` is in `ITEM_FIELDS`, so it is surfaced on the 201 create response and every item read.
- `implementation/registry.py` (whole file) — the `endpoint` decorator has no post-handler recompute hook, so there is no hidden path that could re-run the resolution at creation.

**PRD lines that already pin all of it (kept verbatim):**

- **§3.3, PRD.md:343** — "A new item lands in `lifecycle_state` `DRAFT` with `evidence_tier` `NONE`, `valuation_state` `UNVALUED`, `effective_value_cents` 0, `effective_value_basis` `NONE`, … ; its `acv_value_cents` is computed immediately against the current clock." Matches `routes/items.py:87-106` field for field, including the explicit carve-out that only ACV is computed.
- **§3.4, PRD.md:375** — the recompute-trigger list, which excludes creation. Matches the eight `refresh_item` callsites above.
- **§3.4, PRD.md:371** — the current-clock variant "is what writes `acv_value_cents`". Matches `calc.acv_cents(row, clock.now)` at `routes/items.py:106`.
- **§2.11, PRD.md:274** — "`acv_value_cents` is present in the response even when it is only an input to the effective-value resolution, and it is present as 0 for an item with no `purchase_price_cents`." Closes the "stored but not surfaced" question (`serializers.py:59`) and the null-price case (`calc.py:56-59`).

Both examples the method flagged as candidate silences are therefore already determined: `valuation_state` at creation is pinned to `UNVALUED` by §3.3, and the ACV computed at creation is pinned as present in the response by §2.11.

The Step 7 fix was a test that had drifted from a PRD sentence the implementation read faithfully (`assert 'NONE' == 'ACV'` against §3.3's verbatim `effective_value_basis` `NONE`). Nothing in it reveals a PRD silence or PRD/impl mismatch, so any edit here would be manufactured and would become a mismatch for Step 9 to undo. **Confirming file:line that PRD.md was already correct: `implementation/routes/items.py:102-106`** (the comment and the single `acv_value_cents` write, with no `refresh_item` call anywhere in the creation path).

**Orchestrator independent verification:** `md5sum` of `PRD.md` and `PRD_FINALIZED.md` both `fb551b69b22596c6a59fd98d4c3b6ee8`; both 631 lines; `diff -q` reports no difference. Byte-identity confirmed — this is the "legitimate zero" outcome (Step 7 produced no implementation fix, so there was no impl choice for Step 8 to pin).

## Step 9: Complete PRD — 2026-08-08T15:27:00.000Z

`PRD_COMPLETED.md` is written. Summary below.

## Deltas

| | `PRD_FINALIZED.md` | `PRD_COMPLETED.md` |
|---|---|---|
| lines | 631 | 631 (unchanged — every edit is in-paragraph) |
| chars | 130,827 | 147,034 (**+16,207**) |
| changed lines | — | 65 |
| headings | 29 | 29 (identical) |

**Counts: 41 ambiguity-pins, 24 mismatch-revisions.**

## Changes

**Mismatches (PRD described behavior the code does not exhibit)**

- §2.4 — revise — `updated_at` claimed "refreshed on every mutation"; code refreshes it only inside `touch()`, i.e. only when `version` moves — `store.py:93-106`, `derive.py:182-196`
- §2.4 — revise — "version movement lands on the owning Item **or DocumentationPackage**"; ordinary refreshes flip `stale` and move `stale_line_count` with `bump=False`, so no version moves — `derive.py:304-329`
- §2.7 — revise — `records_freeze_active` defined here as "a live claim exists", but code (and §2.12) define it as `frozen_item_count > 0`; a claim that froze nothing leaves it false — `derive.py:146`
- §2.8 r6 — revise — added "no rung checks cross-household consistency of any body FK" + the household-first check order — `ladder.py:194-207`, `registry.py:35-48`
- §2.8 r12 — revise — "the item behind the target appraisal **or allocation**" contradicted the rung's own Applies-to list; allocation routes to rung 26 — `estates.py:133-139`
- §2.9 Clock advance — revise — added ShareGrants voided by package expiry (they bump); stated Household/LossClaim do not — `derive.py:466-473`, `derive.py:366-387`
- §2.9 Asset delete — revise — added Items unfrozen by a consequent auto-denial — `cascades.py:7-20,23-41`
- §2.9 Appraisal void from CERTIFIED — revise — "each *affected* Policy" → **every** Policy of the household, bumped on a no-op recompute; added voided ShareGrants — `cascades.py:50-53,84-85`
- §2.11 — revise — role redaction applies to item read/list only; redemption rows are never role-redacted — `shares.py:187-208`
- §2.12 inv.1 — revise — "always equals" has an exception: re-scheduling an already-`SCHEDULED` item is unguarded — `items.py:351-365`
- §2.12 inv.3 — revise — allocation creation is not restricted to `CATALOGED` items — `estates.py:133-139`
- §3.1 — revise — "self-registration is the one write an `Anonymous` caller may perform"; Anonymous is exempt from rung 8 and can attach via `household_id` — `people.py:19-52`, `ladder.py:229`
- §3.1 — revise — `address_label` "appears on documentation packages" — it appears on no other resource — `serializers.py:110-124`
- §3.1 — revise — "An unattached owner creates the Household"; unattached is not a precondition — `people.py:88-106`
- §3.2 — revise — "A household holds at most one Subscription" is unenforced; earliest-created wins — `subscriptions.py:43-73`, `derive.py:40-44`
- §3.2 — revise — tier rank is inert (never read) — `constants.py:145,155,165`
- §3.3 — revise — "a `room_id` naming a room of that same household" is unchecked — `items.py:133-153`
- §3.3 — revise — "the submitted category must match an existing category schedule" is unenforced — `items.py:35-38`, `calc.py:25-29`
- §3.3 — revise — `floor_label` "orders the walkthrough"; nothing sorts by it — `rooms.py:44-55`
- §3.4 — revise — "one CategorySchedule per category" unenforced; earliest wins — `valuation.py:21-51`, `calc.py:25-29`
- §3.4 — revise — `credential_id` "unique across appraisers" unenforced; `linked_member_id` unresolved — `valuation.py:69-92`
- §3.6 — revise — "Exactly two fields keep moving after generation" ignores the lifecycle fields delivery writes — `packages.py:224-230`
- §3.7 — revise — a denial has neither the claim-status nor the `settlement_hold` condition, and `denial_reason` is optional on a denial — `claims.py:326-337,350-358`
- §3.8 — revise — "executed plans drop out because their items are already DISPOSED" is wrong for kept items; the real reason is `EXECUTED ∉ live states` — `derive.py:224-232`

**Ambiguity pins (PRD silent)**

- §2.2 — insert — `api_request_timestamp` comes from the logical clock — `envelope.py:24-30`
- §2.3 — insert — out-of-range `limit`/`offset` are clamped, non-integers fall back to defaults, no error — `envelope.py:57-78`
- §2.3 — insert — subscription-list and room-list filter sets (never named anywhere); undeclared query params ignored; lists are never household-scoped — `subscriptions.py:86-97`, `rooms.py:44-55`, `common.py:17-26`
- §2.5 — insert — the clock may be set backwards — `clock.py:16-22`
- §2.7 — insert — which household gates 1 and 2 consult, and that a mutating request reaching no household passes both — `ladder.py:264-287`
- §2.8 r3 — insert — datetime acceptance surface (zone designator optional); undeclared body fields ignored; explicit `null` satisfies the rung — `timeutil.py:26-31`, `ladder.py:141-159`
- §2.11 — insert — redemption `rows` carry the full Item/PackageLine/ClaimLine projection — `shares.py:187-208`
- §3.2 — insert — attestation on `CLOSED` → `ERR_INVALID_STATE`; `attestation_note` discarded — `subscriptions.py:236-261`
- §3.2 — insert — reinstatement error routing (`CLOSED` → terminal, else invalid state) — `subscriptions.py:265-279`
- §3.2 — insert — a household with no subscription has no ceilings but is refused appraisals — `items.py:62-69`, `assets.py:40-50`, `packages.py:104-111`, `valuation.py:199-203`
- §3.3 — insert — room `item_count` moves without a room version bump on a cross-room patch — `items.py:281-285`
- §3.3 — insert — patch null semantics (3 clearable fields vs 3 ignored) and that every patch bumps — `items.py:18-19,264-280`
- §3.3 — insert — empty-string serial: no serial for both serial rules, but a serial for the tier predicate — `items.py:37,41-43`, `calc.py:73`
- §3.3 — insert — upload/delete carry no item-lifecycle precondition; re-deleting a `DELETED` asset still bumps — `assets.py:71-91,132-146`
- §3.3 — insert — evidence cascade hops 3–4 fire only below `PHOTO_SERIAL`; a serial-clearing patch runs no cascade — `assets.py:140-141`
- §3.3 — insert — hop 4's auto-denial carries §3.7's full consequences — `cascades.py:7-20`
- §3.3 — insert — replacement error routing (terminal vs invalid state vs frozen) — `items.py:411-418`
- §3.4 — insert — an item whose category has no schedule always fails the appraiser-scope rung — `valuation.py:165-171`
- §3.4 — insert — generation's expiry sweep is store-wide and bumps nothing — `packages.py:95-101`, `derive.py:412-431`
- §3.4 — insert — hop 3 bumps every policy even on a no-op recompute; hop 4's expiries void scoped grants — `cascades.py:50-53,84-85`
- §3.4 — insert — suspending an already-`SUSPENDED` appraiser succeeds and bumps — `valuation.py:114-124`
- §3.5 — insert — `policy_id` need not be the item's household's; no lifecycle check; re-scheduling allowed — `items.py:330-365`
- §3.5 — insert — unscheduling a non-`SCHEDULED` item → `ERR_INVALID_STATE` — `items.py:368-370`
- §3.5 — insert — a category with no schedule has a sublimit pool of 0 (waterfall and capping) — `calc.py:143-147,280`
- §3.5 — insert — policy patch writes only present non-null fields and always bumps — `policies.py:100-107`
- §3.6 — insert — the rung-31 expiry sweep persists even when generation then fails at rung 35 or 38 — `packages.py:95-101`
- §3.6 — insert — `stale` is a live predicate that can return to false — `derive.py:304-320`
- §3.6 — insert — generation and delivery error routing — `packages.py:85-92,200-211`
- §3.7 — insert — claim-line creation has no claim-status precondition — `claims.py:210-244`
- §3.7 — insert — `basis_downgraded` presupposes basis `APPRAISAL` at create, never resets, never bumps — `derive.py:295-301`
- §3.7 — insert — gross step 1 uses the **exact unrounded** loss-date ACV; unavailable ACV → 0; null `replacement_cost_cents` → 0 — `calc.py:261-270`
- §3.7 — insert — settlement rewrites approved lines without bumping them — `claims.py:446-460`
- §3.7 — insert — the claim-freeze plan push-back clears `balance_spread_pct`/`balanced`, keeps `proposed_at`/`heir_count` — `claims.py:137-140`
- §3.7 — insert — `appeal_note` and `withdraw_reason` discarded — `claims.py:399,480`
- §3.8 — insert — `executor_member_id` unconstrained; `unallocated_item_count` recomputed on every read without a bump — `estates.py:59-76,85-88,94-95`
- §3.8 — insert — allocation delete is a **hard** delete returning the removed row, refused in no state — `estates.py:220-236`
- §3.8 — insert — propose self-loop mode semantics + error routing — `estates.py:240-252,274-287`
- §3.8 — insert — approve/execute error routing — `estates.py:291-298,333-345`
- §3.9 — insert — `PACKAGE`/`CLAIM` grants follow their pointer across households; per-scope definition of `total_effective_value_cents` — `shares.py:187-208`
- §3.9 — insert — revoking a non-`ACTIVE` grant → `ERR_ALREADY_TERMINAL` — `shares.py:152-154`
- §4 — insert — unknown path / wrong method → `ERR_REFERENCE_NOT_FOUND` 404 — `app.py:66-72`

## Veins that came back genuinely clean

- **Timestamp rendering (§2.5).** Every one of the 16 server-written `*_at` fields goes through `derive.stamp`/`render_server`, and all 8 caller-supplied fields go through `keep_raw`. Zero fields in the wrong list; all comparisons are on parsed datetimes. No pins needed — this is the strongest signal in the run.
- **Response-field projections (§2.11).** All 17 entity field lists match `serializers.py` exactly, list == detail everywhere, and both named intermediates (`acv_value_cents`, `gross_value_cents`/`capped_value_cents`) are present as described. Only the *redemption* shape needed pinning, not the entity projections.
- **Version-bump ledger.** 43 of 46 rows were already exactly right, including the hard ones (roll-up parents that only bump when a figure changes, rows created by the request staying at 1, the GET-that-writes on redemption, the OCC parent's own bump).
- **Ordering and tie-breaks.** All four ordered computations plus every list use the same `(created_at, creation-seq)` key; nothing sorts by `id`; the `HIGHEST_VALUE_FIRST` and appraisal-winner tie-breaks match the prose.
- **Filter semantics.** Off-enum filter values return empty pages, `basis` is the sole 422, and `stale`'s boolean matching all behave as written.
- **404/403/422 routing order.** Rung 2 before rung 5 before rung 8, path ids left-to-right, `ERR_HOUSEHOLD_NOT_FOUND`/`ERR_ITEM_NOT_FOUND` special-casing — all exactly as the ladder states.
- **Rounding order (§2.6).** Per-line-then-sum in packages, single end-rounding on the ACV curve, separately-rounded proration credit and charge, floor-then-distribute-remainder for heir shares — all pinned correctly already.

**Orchestrator independent verification:** `PRD_COMPLETED.md` on disk at 631 lines / 147,034 chars (**+16,207 chars, 0 line delta** vs `PRD_FINALIZED.md`); heading count 29 in both, so no new sections were added; `diff` reports **65 changed lines**, matching the reported 41 + 24 = 65 edits. `find implementation/ test_suite/ test_helpers/ -newer results.1.json` **still empty** after Step 9 — Step 9 touched only `PRD_COMPLETED.md`, so the green 83/83 × 8 result continues to describe the shipped tree.

---

# Pipeline complete — task_0927_home_inventory_valuables

**83/83 tests passing on all 8 stability-sweep rounds, 0 test deletions, 0 `test_helpers/` fixes, 0 `implementation/` fixes.** One `test_suite/` assertion split under STEP 1c (partial coverage). Step 8 legitimately produced a byte-identical `PRD_FINALIZED.md`; Step 9 carried the whole completeness job with 65 edits (41 ambiguity-pins + 24 mismatch-revisions), the largest Step-9 yield recorded on this pipeline.
