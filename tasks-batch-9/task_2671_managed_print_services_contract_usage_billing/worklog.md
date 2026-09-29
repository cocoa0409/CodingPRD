# Worklog — task_2671_managed_print_services_contract_usage_billing

## Step 1: Create task directory — 2026-09-04T04:28:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2671_managed_print_services_contract_usage_billing/` and `.../workspace/` using the pre-assigned path from the orchestration prompt (no index auto-allocation, per instruction — other pipelines run concurrently on this host).

## Step 2: Generate scaffold artifacts — 2026-09-04T06:20:00.000Z

Generated the three scaffold files from the scenario text plus the scaffold-generator skill
specification only (no sibling task under `tasks/` was inspected).

- `SCAFFOLD.yaml` — §1.0–§1.7: 14 entities, 10 state machines, 2 OCC rules, 9 calculation rules,
  31 priority-ordered validations, 64 endpoints, 54 error codes, 5 roles. Contains neither
  `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level key, 22 instances covering all nine
  difficulty rules (2/3/3/2/3/3/2/2/2).
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level key, 83 instances (58 full recipes +
  25 `excluded_because` stubs) across all nine claim-extraction sections: entities 12,
  state_machines 20, calculations 14, validations 10, endpoints 6, errors 11, rbac 4,
  complexity_layers 5, consistency_model 1.

Checks run: `scaffold_lint.py` -> `VERDICT: clean lint` (1288 calls scanned); all 105 instance
names unique across both design files; no unbound `${...}` placeholder in any recipe; no stub
carries a `test_recipe`; every one of the 54 declared error ids is exercised or explicitly
delegated to a §1.8 instance; every `close` call is reachable (no OPEN -> CLOSED transition is
assumed anywhere); manual `POST /consumable-orders` calls only occur from SUPPLY_LOW/SUPPLY_BLOCKED.

### Step 2 — subagent returned summary (verbatim)

Scaffold generation for task 2671 is complete. All three files are in `/home/ubuntu/github/CodingPRD/tasks/task_2671_managed_print_services_contract_usage_billing/`, generated only from the scenario text plus the scaffold-generator skill spec (no sibling task was read).

## Files
| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3032 | 153 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2380 | 148 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4913 | 307 KB |

## SCAFFOLD.yaml (§1.0–§1.7)
14 entities (ServiceContract, CostTier, Site, SparePartStock, Device, Technician, MeterRead, BillingPeriod, BillingStatement, StatementLine, ConsumableOrder, ServiceTicket, QuarterlyReview, RemovalOrder), 10 state machines (Device carries independent lifecycle × supply dimensions; MeterRead and ServiceContract cycle), 2 OCC rules, 9 calculation rules, 31 priority-ordered validations, **64 endpoints**, 54 error codes, 5 roles. Contains neither design key. Domain money is micro-dollars per page (10,000 = 1 cent), tiering is NON-GRADUATED, statement rounding is pinned round-per-line-then-sum, with PROVISIONAL(PROJECTED)/FINAL(ACTUAL) variants, minimum-volume shortfall, SLA credits with parts-hold excusal, waste/hoarding controls, TCO assessed-vs-realized and a gross-keyed settlement discount.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
22 instances, all nine rules >=2: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
83 instances across all nine claim-extraction sections — 58 full recipes plus 25 `excluded_because` stubs: entities 12, state_machines 20, calculations 14, validations 10, endpoints 6, errors 11, rbac 4, complexity_layers 5 (both OCC rules, the 15 %-toner rate threshold, derived-field reconciliation, plus a dual-variant stub), consistency_model 1.

## Verification
- `scaffold_lint.py` -> **`VERDICT: clean lint`** — 64 endpoints, 14 entities, 22 §1.8 + 58 §1.9 instances, **1288 calls scanned**, all FKs reverse-reachable.
- 105 instance names unique across both design files; no unbound `${...}` placeholder in any recipe; no stub carries a `test_recipe`; all 54 declared error ids are either triggered or explicitly delegated to a named §1.8 instance.
- Two model-legality sweeps caught real bugs and were fixed: BillingPeriod has no OPEN->CLOSED edge (every `close` is now preceded by a sweep or provisional-statement), and a manual `POST /consumable-orders` is only legal from SUPPLY_LOW/SUPPLY_BLOCKED — the toner-cap validation instance and the consumable/review error instance were reworked to reach the order through the auto-replenishment path (which also changed the expected code from `ERR_DEVICE_INVALID_STATE` back to `ERR_TONER_CAP_EXCEEDED`).

Orchestrator verification: all three files present, `SCAFFOLD.yaml` contains zero occurrences of either design key.

## Step 3: Copy shared files — 2026-09-04T06:18:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T06:36:00.000Z

Orchestrator truncation check (per the known doc-generator failure mode): `wc -l` = 464; `grep -n '^#'` shows all 5 top-level sections present (§1 Introduction, §2 Global Specifications with 11 subsections, §3 Business Logic with 9 subsections, §4 Endpoint Definitions at line 331, §5 Error Code Catalogue at line 404); `tail -25` ends on a complete markdown table row (`| ERR_TONER_CAP_EXCEEDED | 409 |`), i.e. a real section boundary, not mid-sentence. NOT truncated — no regeneration needed.

### Step 4 — subagent returned summary (verbatim)

All three Hard Contracts verified clean. Final report:

## Output

`workspace/PRD.md` — **464 lines**, ending at a completed final section. Last section heading: **`## 5. Error Code Catalogue`** (final line is the table row `| ERR_TONER_CAP_EXCEEDED | 409 |`, not mid-sentence).

Built via 12 chunked `cat >>` appends (line counts checked after each: 77 -> 125 -> 173 -> 205 -> 233 -> 269 -> 311 -> 402 -> 464); no single giant Write, so no 64k truncation.

## Section list

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control - 2.2 API Response Structure (byte-identical verbatim block) - 2.3 Pagination, Ordering and Collection Filters - 2.4 Resource Identity, Timestamps and the Logical Clock - 2.5 Micro-Dollars, Cents and Rounding Discipline - 2.6 Two-Dimensional Device State and Cascade Propagation - 2.7 Path Resolution and Nested Reads - 2.8 Optimistic Concurrency on Parent Versions - 2.9 Rejection Precedence - 2.10 Segregation of Duties and Audit Attribution - 2.11 Half-Open Windows and Interval Arithmetic
- `## 3. Business Logic & Workflows` — 3.1 Contract Formation, the Rate Card and the Suspension Cycle - 3.2 Customer Sites, Secure Print Release and the Parts Locker - 3.3 Fleet Assessment, Placement and the Road to Billable Service - 3.4 Meter Capture, Validation and Exception Handling - 3.5 Consumables: Auto-Replenishment, Hoarding Control and Waste Control - 3.6 Service Dispatch: Regions, Certification, Parts and Response-Time Credits - 3.7 Billing Periods: the Provisional Projection and the Final Actual - 3.8 The Quarterly Business Review: Savings, Trends and Right-Sizing - 3.9 End of Contract: Removal, Data Sanitization and Settlement
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Coverage

| Scaffold element | Count | Covered |
|---|---|---|
| Entities | 14 | 14 |
| Entity field names | 147 | 147 (all in backticks) |
| Endpoints | 64 | 64 table rows |
| Error codes | 54 | 54 in prose + table (55 rows, see note) |
| Validations | 31 | 31, in strict priority order in §2.9 |
| Calculations | 9 | 9 as precise prose |
| Concurrency rules | 2 | 2 |
| Roles | 5 | 5 |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Required set built programmatically from `entities[].fields[].name` (147 unique) and checked against every backticked token in PRD.md using a fence-aware tokenizer. `MISSING: []`. All 54 error IDs, all state names, all enum values and all 5 role names also verified present verbatim in backticks. The only uppercase scaffold tokens absent are calculation-constant *names* and pseudocode-local variables — correctly absent, since the skill requires constants be expressed as numeric values inside business prose.

**Contract 2 — Rule Coverage: PASS.** All 31 validations expressed as an ordered precedence list in §2.9 with error IDs and full `applies_to` scopes. Both `concurrency_rules` expressed with write endpoint + `expected_billing_period_version` / `expected_device_version` + `ERR_STALE_PERIOD_VERSION` / `ERR_STALE_DEVICE_VERSION` + 412. Every state-machine transition (10 machines including Device's two-dimensional lifecycle/supply pair) given with preconditions and side effects, including the 4-hop read-acceptance cascade, the 4-hop sanitize cascade, and the void compensation chain. All 9 calculations rendered as reconstruction-testable prose with both variants of the dual-variant rules. Sibling-branch symmetry given equal density.

**Contract 3 — §3 Path Purity: PASS.** Scanned all 342 backticked tokens in §3 (lines 174–330): tokens starting with `/` = 0; method+path lines = 0; bare HTTP method verb lines = 0.

## One scaffold inconsistency to flag

`ERR_SANITIZATION_EVIDENCE_MISSING` (validations priority 15, HTTP 422) is referenced in `validations[]` but **absent from the scaffold's `errors[]` catalog** (54 entries). I expressed the rule in §2.9 item 15 and §3.9 prose and added the row to the §5 table (hence 55 rows vs 54 scaffold errors). Separately, several transition preconditions have no dedicated error code (suspend requires no `PROVISIONAL` period; network integration requires a non-null `network_vlan_tag`; removal-order creation requires no in-flight order); these are attributed to the priority-7 transition-existence codes `ERR_CONTRACT_INVALID_STATE` / `ERR_DEVICE_INVALID_STATE`.

The two withheld design files were never opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-04T07:35:00.000Z

Launched concurrently with Step 6 in a single assistant message (two Agent tool uses), so the
implementation generator could not read `test_suite/` — the directory did not exist at its spawn.
Orchestrator post-check: `test_helpers/` and `test_suite/` are at the TASK ROOT; `find workspace -name
test_helpers -o -name test_suite` returns nothing, so no stray copies landed under `workspace/`.

### Step 5 — subagent returned summary (verbatim)

Test-suite generation for task 2671 is complete and audit-clean.

## Output (all at the task root, nothing inside `workspace/`)

`test_helpers/` — 2301 lines: `types.py` 458, `api_client.py` 292, `api_errors.py` 134, `assertions.py` 361, `constants.py` 83, `factories.py` 202, `fixtures.py` 666, `test_users.py` 63, `__init__.py` 42

`test_suite/` — 11 055 lines, `conftest.py` 57 plus 17 test files:

| file | lines | tests |
|---|---|---|
| test_01_contract_and_fleet_registration.py | 892 | 21 |
| test_02_lifecycle_transitions.py | 822 | 19 |
| test_03_billing_calculations.py | 853 | 14 |
| test_04_business_rule_validations.py | 932 | 15 |
| test_05_endpoint_behaviour.py | 839 | 19 |
| test_06_error_catalogue.py | 904 | 20 |
| test_07_role_permissions.py | 766 | 10 |
| test_08_concurrency_and_derived_counters.py | 870 | 12 |
| test_09_statement_variants_and_savings.py | 327 | 7 |
| test_10_money_formulas.py | 621 | 9 |
| test_11_nonlinear_workflows.py | 736 | 9 |
| test_12_cascades.py | 343 | 9 |
| test_13_rejection_precedence.py | 365 | 9 |
| test_14_boundary_precision.py | 527 | 13 |
| test_15_cross_entity_gates.py | 367 | 9 |
| test_16_temporal_windows.py | 473 | 6 |
| test_17_compensating_ledgers.py | 361 | 6 |

## Coverage

- **Queue A (depth): 77 tests across 22/22 instances**, every instance with >=2 tests.
- **Queue B (breadth): 130 tests across 58/58 non-stub instances**, every instance with >=1 test.
- 207 test functions, 239 collected cases after parametrization. 80 distinct design tags = exactly the 22 + 58 translatable instances.

## Skipped instances

**No instance was skipped by the PRD-first filter** — all 80 passed both conditions. The 25 `excluded_because:` stubs were deliberately not translated (7 state_machines, 7 calculations, 4 validations, 6 errors, 1 complexity_layers); all 25 `difficulty_instance:` cross-references verified to resolve to real rule/instance pairs.

Individual **assertions** (not instances) were dropped where the PRD does not uniquely derive them: cost-tier PUT/PATCH/DELETE status (404 vs 405 both faithful), `color_tier_index` with no COLOR rows, an auto order's `committed_cents`, device `version` deltas in multi-hop cascades, and stored `labor_hours` on a resolved ticket. Timestamps other than `created_at`/`updated_at` are compared as parsed instants, since the PRD pins three-digit fractional rendering only for those two.

## Design-index literals overridden in favour of the PRD (worth knowing before the sweep)

1. `provisional_statement_with_zero_accepted_reads_charges_pure_shortfall` asserts period `status == OPEN` after generation; the PRD says generation drives `OPEN -> PROVISIONAL`. Tests assert `PROVISIONAL`.
2. The index gives HTTP 422 for `ERR_RATE_CARD_INCOMPLETE`; the PRD catalogue gives 409. Tests assert 409.
3. Freshly created / not-yet-billed periods: the index asserts `provisional_total_cents`/`final_total_cents == 0`; the PRD keeps them null until the matching statement exists. Tests assert `None`.

## Verification performed

`python3 -m py_compile` on all 26 generated `.py` files; `pytest --collect-only` collects 239 cases with zero import or collection errors; no duplicate test definitions; no `skip`/`skipif`/`xfail` anywhere; no occurrence of the word "scaffold" or any design-document section reference; every `from test_helpers import ...` name resolves; all 64 SCAFFOLD endpoints map 1:1 onto `api_client` methods and every factory's keys match the endpoint's declared inputs.

One small helper change was needed: `BILLING_ANALYST_2_USER_ID` was added to `test_helpers/test_users.py` and exported. `workspace/implementation/` was not modified.

## Step 6: Generate implementation — 2026-09-04T07:35:00.000Z

### Step 6 — subagent returned summary (verbatim)

The implementation is complete and verified.

## Modules (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 73 | Flask app factory, blueprint registration, `ApiError`/404/405/415/400/unhandled JSON error envelopes, `0.0.0.0:$PORT` |
| `util.py` | 96 | logical-clock default `2026-08-01T00:00:00Z`, ISO 3-frac formatting, `ROUND_HALF_UP` helpers, micro-dollar->cent, ceil-hours, `add_months`, half-open `overlaps` |
| `errors.py` | 82 | all 54 error ids -> HTTP status, `ApiError` + `fail()` |
| `store.py` | 100 | in-memory `db` singleton (14 dicts), `new_row`, once-per-request `touch()` |
| `envelope.py` | 53 | success/array/error envelopes, `req_` + 20 upper-alnum request ids |
| `validation.py` | 168 | priority-4 shape checks, pagination (`limit` 1..100, `offset` >=0), lenient query filters |
| `auth.py` | 36 | 5 roles, `ERR_UNAUTHENTICATED` -> `ERR_ROLE_NOT_PERMITTED` |
| `resolve.py` | 39 | 11 path/body FK resolvers (priority 3 / 5) |
| `derive.py` | 230 | every computed-on-read field (no version bumps) |
| `serialize.py` | 279 | 14 entity serializers |
| `calc.py` | 358 | all 9 calculation rules |
| `cascade.py` | 152 | read accept/reject/void, auto-replenishment, order create/cancel/deliver, sanitize fan-out |
| `routes/` | 1 431 | 11 blueprints: contracts 182, sites 148, devices 180, technicians 52, meters 235, billing 181, consumables 107, tickets 248, reviews 105, removals 174, clock 19 |
| `requirements.txt`, `start.sh` | — | guarded `pip install`, `exec python3 app.py`, reads `$PORT` (default 10000), foreground |

Total 3 297 lines of Python. Every `.py` file compiles cleanly.

## Endpoint count
`app.url_map` enumerates exactly **64 endpoints**, matching §1.5 one-for-one.

## Smoke boot: succeeded
Two real boots via `bash start.sh` (ports 18471, 18472), each killed by its own PID only — no broad `pkill`. Verified end-to-end through 5 scripted passes covering contract formation, rate card, secure release, device placement, meter capture with exceptions and void cascade, auto-replenishment, PROVISIONAL/FINAL statements with OCC 412, ticket dispatch with parts hold and SLA credit, quarterly review with right-sizing, and removal/sanitize/settle to contract CLOSED.

Fresh-process guarantees confirmed on the second boot: all collections empty, logical clock exactly `2026-08-01T00:00:00.000Z`, no seeded data, no on-disk state.

Two notes: rejection ordering follows the §2.9 ladder as authoritative where §3 prose differs (certification before region on dispatch; transition state before ownership on ticket actions), and `secure-release-config` with `probe_result: PASS` requires `network_vlan_tag` in the body even when the site already carries one, per PRD §3.2.

## Step 7 — test/fix iteration to a clean sweep

Two iterations, each an 8-round parallel stability sweep under `setsid nohup`
(`--isolation per-test-server`, 239 tests per round).

| Iteration | Rounds passing | Failing (union) |
|---|---|---|
| 1 | 0 / 8 | 7 tests, identical in all 8 rounds — deterministic, no flakiness |
| 2 | 8 / 8 | none (239/239 every round) |

No test was deleted: every failing assertion traced to a verbatim PRD sentence.
All seven failures were test-layer defects in two families.

### Fixes to `test_helpers/`
- `assertions.py` — `assert_fields` now compares ISO 8601 timestamp fields by
  *instant* rather than by byte-identical string (new `_as_instant` parser).
  Six tests asserted `period_start` / `period_end` / `scheduled_for` /
  `last_read_at` equal to a client-supplied literal such as
  `2026-09-01T00:00:00Z` while the server echoed `2026-09-01T00:00:00.000Z`.
  PRD §2.4 pins three-fractional-digit rendering only for the server-minted
  `created_at` / `updated_at` pair and never states how an echoed
  client-supplied instant is re-serialised, so the instant is the asserted
  value and the fractional-digit form is not. The runner's own
  `is_iso8601_timestamp` accepts both forms, confirming the format is unpinned.

### Fixes to `test_suite/`
- `test_01_contract_and_fleet_registration.py` —
  `_closed_period_with_two_priced_devices()` now makes the period closeable by
  sweeping it instead of by publishing a provisional statement.
  `TestPerDeviceStatementLines::test_each_device_reverse_lookup_returns_only_its_own_priced_line`
  asserts each device owns exactly one historical line, but the helper left a
  PROVISIONAL statement behind alongside the FINAL one. PRD §3.7 deletes a
  provisional statement only when a *later provisional supersedes it*, never at
  close, and §4 defines the endpoint as "every StatementLine ever written for
  this device" — so the implementation's two rows were correct and the setup was
  at fault. Both devices already hold an accepted reading covering the period,
  so the sweep manufactures no placeholder and `exception_open_count` stays 0.

### Fixes to `implementation/`
None. No implementation defect was found; both failure families were test bugs.

## Step 7: Run tests and iterate — 2026-09-04T08:15:00.000Z

Orchestrator independent verification (per the known failure mode where a Step 7 subagent reports a
clean sweep without leaving artifacts): all eight `workspace/implementation/results.$i.json` exist,
~82 KB each, same mtime 07:53, and `json.load` on each reports `passed=239 total=239 failed=0`.
Confirmed, not taken on the subagent's word.

Step 8 skip condition does NOT apply: the sweep needed 2 iterations, with 1 `test_helpers/` fix and
1 `test_suite/` fix, so PRD silences were revealed and Step 8 must run.

### Step 7 — subagent returned summary (verbatim)

Clean exit on iteration 2.

## Summary

**Iterations run:** 2. Each was an 8-round parallel stability sweep under `setsid nohup` (`--isolation per-test-server`, 239 tests/round).

| Iteration | Rounds passing | Failures (union) |
|---|---|---|
| 1 | 0 / 8 | 7 tests, **identical in all 8 rounds** — fully deterministic, no flakiness |
| 2 | **8 / 8 — 239/239 every round** | none |

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and survived the unique-derivability check; all 7 failures were test-layer defects in two families.

**Fixes to `test_helpers/`**
- `test_helpers/assertions.py` — `assert_fields` now compares ISO 8601 timestamp fields by **instant** rather than by byte-identical string (added `_as_instant`). Six tests asserted `period_start` / `period_end` / `scheduled_for` / `last_read_at` equal to a client-supplied literal like `2026-09-01T00:00:00Z` while the server echoed `2026-09-01T00:00:00.000Z`. PRD §2.4 pins the three-fractional-digit rendering **only** for the server-minted `created_at`/`updated_at` pair and never says how an echoed client-supplied instant is re-serialised — so the instant is the asserted value and the fractional-digit form is unpinned (two PRD-faithful renderings exist). Corroborated by the runner's own `is_iso8601_timestamp`, whose docstring reads "with optional milliseconds" and which accepts both forms. Semantic strength is unchanged: exact match is still tried first, and a wrong instant still fails.

**Fixes to `test_suite/`**
- `test_01_contract_and_fleet_registration.py` — `_closed_period_with_two_priced_devices()` now makes the period closeable by **sweeping** it instead of by publishing a provisional statement. `TestPerDeviceStatementLines::test_each_device_reverse_lookup_returns_only_its_own_priced_line` asserts each device owns exactly one historical line, but the helper left a PROVISIONAL statement alongside the FINAL one, so the endpoint correctly returned two. PRD §3.7 deletes a provisional statement only when *a later provisional supersedes it*, never at close; §4 defines the endpoint as "every StatementLine ever written for this device"; and §2.3's statement `variant` filter presupposes both variants coexisting — so the implementation was right and the setup was at fault. Both devices already hold an accepted reading covering the period, so the sweep manufactures no placeholder and `exception_open_count` stays 0, keeping the close legal and the FINAL statement's figures (4,688 + 938 = 5,626 cents) unchanged.

**Fixes to `implementation/`:** none — no implementation defect was found.

Two notes on the hypotheses I was handed. The implementation generator's §2.9-over-§3 precedence resolutions and its `probe_result: PASS` => `network_vlan_tag`-required reading are both directly supported by PRD text (§2.9's ladder is declared "exhaustive and strictly ascending"; §3.2 states the PASS outcome "requires `network_vlan_tag` to be supplied in the range 1 through 4094"), and the tests covering them passed in all 16 rounds. Cleaned up `sweep.log` and `__pycache__`; the eight passing `results.*.json` files remain in `workspace/implementation/` as sweep evidence.

## Step 8: Finalize PRD — 2026-09-04T08:22:00.000Z

Step 8 ran (skip condition not met: 2 iterations, 1 `test_helpers/` fix, 1 `test_suite/` fix).
Orchestrator check: `PRD_FINALIZED.md` exists, 466 lines vs PRD.md's 464.

### Step 8 — subagent returned summary (verbatim)

Done. `PRD_FINALIZED.md` written with exactly one edit.

**Line counts:** PRD.md 464 -> PRD_FINALIZED.md 466 (+2 lines, +0.43%).

**Changes**
- §2.4 (Resource Identity, Timestamps and the Logical Clock) — insert — pinned that *every* instant-valued resource field (not just `created_at`/`updated_at`) is emitted as ISO 8601 UTC with exactly three fractional digits and trailing `Z`, or `null` when empty; client-supplied instants are stored as the instant and re-serialised in that canonical form (`2026-09-01T00:00:00Z` reads back `...00.000Z`), including derived copies such as `last_read_at`; temporal comparisons compare instants, not strings — `implementation/util.py:30` (`fmt_dt`), applied at `implementation/serialize.py:9-10, 48, 93, 134-139, 152-153, 182, 196, 212, 227-233, 267, 277`.

**Pre-edit search log (edit 1)**
- (a) Subject: serialisation form of all instant-valued output fields, and the round-trip of client-supplied instants.
- (b) Paths enumerated: `util.py:fmt_dt` / `parse_dt`; every call of `fmt_dt` in `serialize.py` (all 12 resource shapes, including the lean `cost_tier` and `statement_line` `created_at`); grep for `isoformat`/`strftime`/manual timestamp formatting outside `serialize.py` (only `envelope.py:_request_timestamp`, which uses the identical three-digit `Z` form already pinned in §2.2); every non-serializer response payload in `routes/` and `app.py` (all are `serialize.*` or `ok({})`, so `routes/clock.py` echoes no instant); client instant intake via `validation.py:dt_field` -> `parse_dt` at `routes/billing.py:23`, `routes/meters.py:30`, `routes/removals.py:27,88`; derived copies at `cascade.py:61,91,96` (`last_read_at` <- `coverage_end`), `cascade.py:130` (`delivered_at`), `routes/tickets.py:167,217`, `routes/removals.py:170`, `store.py:64,95,99`; instant comparisons in `calc.py:171,189,233`, `derive.py:143,174,211`, `routes/meters.py:42,200`, `routes/billing.py:132` (all datetime-typed, never string-typed).
- (c) Adjustments made: replaced an initially exhaustive-looking field enumeration with a universal "every instant-valued field a resource exposes" plus illustrative examples, so no emitted field is accidentally excluded; added the "or `null` when the field holds no instant" clause because `fmt_dt(None)` returns `None` for the many nullable stamps; softened the closing sentence from "never two different values; only the instant is significant" to "denote the same stored value, and every temporal comparison ... compares points in time rather than strings," which matches the datetime-typed comparisons enumerated above without making claims about input-validation acceptance.

**No edit made** for the `test_suite/test_01` fixture fix: PRD §3.7 already restricts provisional-statement deletion to supersession by a later provisional (verified — `routes/billing.py:120-150` `close_period` deletes nothing), and §4 line 359 already defines `GET /devices/{id}/statement-lines` as "every StatementLine ever written for this device". That failure was a pure setup defect, not PRD silence. The Step 7 notes' other items (§2.9-over-§3 precedence; `probe_result: PASS` requiring `network_vlan_tag`) carried no fix and are already determined by PRD text, so they are out of scope.

## Step 9: Complete PRD — 2026-09-04T09:00:00.000Z

Run as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a
single subagent, because a full 64-endpoint / 14-entity / 9-calculation scan does not fit one
context — a single-pass agent tends to produce a file byte-identical to its input, which is the tell
that the scan never actually ran. Partition: pass 1 = app/util/errors/store/envelope/validation/
auth/resolve/serialize/derive; pass 2 = calc.py + cascade.py; pass 3 = the 11 route blueprints.
Each later pass was handed the earlier passes' consistency notes and told to edit in place, never
re-copy.

Orchestrator integrity check on the result: `PRD_COMPLETED.md` is NOT byte-identical to
`PRD_FINALIZED.md` (`cmp` differs; 70 changed lines / 35 revised passages; 110,196 -> 122,459 chars,
+11.1%); 466 lines; 5 top-level sections intact; §4 holds all 64 endpoint rows; §5 holds all 55
error rows; file ends on the complete final table row `| ERR_TONER_CAP_EXCEEDED | 409 |`, a real
section boundary. Also confirmed via `find -newermt` that no file under `implementation/`,
`test_helpers/` or `test_suite/` was modified after the 07:53 passing sweep, so the 8/8 x 239/239
evidence in `results.{1..8}.json` still describes the shipped artifacts.

Totals across the three passes: 31 edits — 26 ambiguity-pins, 9 mismatch-revisions (pass 1: 12 + 2;
pass 2: 4 + 2; pass 3: 12 + 5). All in-paragraph inserts/revisions; no new sections; line count
unchanged from 466 apart from Step 8's single +2.

### Step 9 pass 1 — subagent returned summary (verbatim)

Pass 1 complete. `PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` and patched in place with 14 inline edits (no new sections, no new lines).

**Line counts / delta:** both files 466 lines; 110,196 -> 116,164 chars (**+5,968**).

**Counts:** 12 ambiguity-pins, 2 mismatch-revisions.

**Changes**

- §2.1 Role-Based Access Control — insert — ambiguity — an `X-User-ID`/`X-User-Role` header present but empty counts as absent for `ERR_UNAUTHENTICATED` — `auth.py:19-24`
- §2.2 Success Response Format — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alphanumeric characters — `envelope.py:8-12`
- §2.2 Success Response Format — insert — ambiguity — `api_request_timestamp` is read from the host's real UTC clock, not the logical clock (the one such instant in the API) — `envelope.py:15-20`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` also 422, empty-string param treated as absent, offset past `total_count` returns an empty page with `has_more` false — `validation.py:128-161`
- §2.3 Ordering — insert — ambiguity — `created_at` ties (frequent, since the logical clock only moves on demand) resolve by creation order, in the same direction as the `created_at` comparison; covers newest-accepted-read and latest-closed-period tiebreaks — `store.py:46-50`, `derive.py:168-177`, `derive.py:199-221`
- §2.3 Collection filters — insert — ambiguity — filters match as exact strings and are never validated against the field's enum, so an unmatched value yields an empty page, not 422 — `validation.py:164-168`
- §2.4 Identity/Timestamps — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `store.py:60-66`
- §2.4 Identity/Timestamps — revise — **mismatch** — the universal "any side-effect field change bumps `version`" claim softened: the `removal_order_id` and `right_sizing_action` annotations do not, and read-derived values are not stored business fields of the exposing row — `store.py:82-100`, `derive.py:1`
- §2.4 Instant rendering — insert — ambiguity — accepted input spellings (`Z`, numeric offset, no zone -> UTC), sub-millisecond digits truncated not rounded, unparseable instants are 422 — `util.py:12-38`, `validation.py:103-114`
- §2.6 Cascade propagation — revise — **mismatch** — a row written by several hops of one call advances `version` by exactly 1 (not per hop), and the enumerated derived counters are recomputed on read rather than stored, so a hop moving only them leaves the exposing row's `version`/`updated_at` alone; stored counters listed explicitly — `store.py:82-100`, `derive.py:70-231`, `serialize.py:29-30,62,73,94-98,119,156,268`
- §2.9 item 4 (Request shape) — insert — ambiguity — JSON `null` counts as absent (default when optional, missing when required), whitespace-only fails non-empty, integer fields reject booleans and fractional values, absent/empty body reads as `{}` — `validation.py:10-100`
- §2.5 Rounding discipline — insert — ambiguity — `volume_trend_pct` is emitted as a plain JSON number (no preserved trailing zeros, `0.0` when flat) and half-up ties go away from zero for negatives — `util.py:52-55`
- §3.4 Period sweep — insert — ambiguity — `offline_exception_count` and `exception_open_count` are current-status counts, so resolving a placeholder lowers both again — `derive.py:158-160,186-188`
- §3.6 Ticket resolution — insert — ambiguity — `labor_hours` accepts fractional numbers, is stored/echoed as reported, and the >8 test applies to the raw value — `validation.py:65-77`, `routes/tickets.py:205-218`, `serialize.py:235`
- §5 Error catalogue intro — insert — ambiguity — unmatched route -> `ERR_INVALID_REQUEST` 404, undeclared method -> `ERR_INVALID_REQUEST` 405 (both before authentication), unparseable/non-object body -> `ERR_INVALID_REQUEST` 422 — `app.py:42-57`

Consistency notes for the later passes: the §2.6 stored-vs-derived list and the §2.4 "annotates without a version bump" clause were written to cover `cascade.py` and `routes/` behaviour I read but did not edit (`routes/removals.py:58-60` and `routes/reviews.py:61-62` deliberately skip `touch`); passes 2 and 3 should keep their wording aligned with those two clauses rather than restating the general rule.

### Step 9 pass 2 — subagent returned summary (verbatim)

Pass 2 complete.

**File size:** before: 466 lines / 116,164 chars -> after: 466 lines / 117,955 chars (all edits are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 4 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- `§3.7` step two (line 286) — revise — mismatch — Pinned the precedence inside tier selection: the "no rate-card row for this `page_class` at all" test runs *first*, so a class with a **positive** volume and no rows records tier index 0 / rate 0 and still emits its lines (amount 0) instead of failing; `ERR_TIER_COVERAGE_GAP` fires only when the class has at least one row and none contains the volume. Also pinned the previously silent case of rows existing with no `tier_index` 1 row at zero volume -> 0/0. — `calc.py:72-88`
- `§2.9` rule 27 (line 158) — revise — mismatch — Narrowed the global rejection-precedence entry to match: coverage is required only for a class that has at least one rate-card row. — `calc.py:75-76`
- `§3.8` right-sizing (line 310) — revise — ambiguity — PRD claimed non-fleet devices "keep `right_sizing_action` at `NONE`"; impl only writes fleet devices, so a device classified while in the fleet retains `UPGRADE`/`CONSOLIDATE` after being retrieved/removed (and is still picked up by the approval cascade, which walks all contract devices). Reworded to "not classified at all; keeps whatever it already carries". — `calc.py:316-339` (+ `routes/reviews.py:61-62,101-104`)
- `§3.5` waste control (line 246) — insert — ambiguity — Pinned that `waste_flagged` and the page snapshot are decided once at order creation and never re-evaluated (dropped the misleading "derived"), and that on the automatic path the snapshot is taken *after* the triggering reading was accepted, so it includes that reading's pages. — `cascade.py:11-27,52-68`
- `§3.5` delivery (line 250) — revise — mismatch — "resets `pages_since_last_cartridge` to 0" is only true when no accepted reading has a `coverage_end` after the stamped `delivered_at`; softened to state the watermark result exactly. — `cascade.py:128-135`, `derive.py:148-155`
- `§3.5` cancellation (line 252) — insert — ambiguity — Pinned that the toner-level supply resolution belongs to the direct cancel endpoint only (and only from `SUPPLY_ORDERED`), and that the three cascade cancellations do **not** re-resolve it: sanitization leaves `supply_state` untouched, the superseding manual order drives `SUPPLY_ORDERED`, the void returns `SUPPLY_OK`. — `cascade.py:111-125,139-153`, `routes/consumables.py:52-58`

**Verified-and-left-alone (already uniquely pinned):** rollback-before-spike and the `> 3 x duty_cycle` strict test; SLA credit's 8-hour parts grace excusal, 4-hour ceil step, x2 CRITICAL, 50% factor cap, single half-up rounding, 25,000-cent cap; ceil-hours-then-multiply labour with `FULL` -> 0; per-device/per-meter provisional projection with ceil period-days and floored-at-1 elapsed-days; inclusive band bounds and non-graduated single rate; round-per-line-then-sum; per-class shortfall at the entry rate; ticket/waste window selection; settlement waterfall including the gross-keyed 10% discount at >= 500,000 cents and the once-only fee rounding; TCO per-device rounding, latest-closed-period tie-breaks, exact-rational right-sizing thresholds, `volume_trend_pct`; the four-hop acceptance cascade, the void reversal and its `exception_open_count` invariance, and the sanitize fan-out (device -> orders, one `version` bump per row per call).

### Step 9 pass 3 — subagent returned summary (verbatim)

Pass 3 complete.

## Before / after
| | lines | chars |
|---|---|---|
| before | 466 | 117,955 |
| after | **466** | **122,459** |

All 17 edits were in-paragraph inserts/revisions, so the line count is unchanged by design. No new sections.

## Counts
- **ambiguity-pins: 12**
- **mismatch-revisions: 5**

## Changes
- `§3.1` — insert — ambiguity — cost-tier `tier_index` 1 => `from_page` 1, and `to_page < from_page`, are `ERR_INVALID_REQUEST` (422) checked before both uniqueness tests; the "one null `to_page`" rule falls out of the band test — `routes/contracts.py:81-98`
- `§3.2` — insert — ambiguity — secure-release probe/method and PASS/VLAN requirements are `ERR_INVALID_REQUEST` (422) evaluated **before** the ownership check; a `FAIL` probe writes neither field and discards a supplied VLAN — `routes/sites.py:76-105`
- `§3.2` — revise — mismatch — parts-locker: a newly created row stays at `version` 1 (it is not incremented), and the response is 200 with the locker row even on the creating call — `routes/sites.py:125-136`
- `§3.3` — insert — ambiguity — device creation resolves `contract_id` then `site_id`; both-bad reports `ERR_CONTRACT_NOT_FOUND`, and `asset_tag` uniqueness runs after both — `routes/devices.py:33-39`
- `§3.4` — insert — ambiguity — intake resolves `device_id` then `billing_period_id`; both-bad reports `ERR_DEVICE_NOT_FOUND` — `routes/meters.py:33-34`
- `§3.4` — insert — ambiguity — sweep placeholders stamp `read_at`, zero deltas, `voided_reason` `NONE`, null resolution fields, and `submitted_by_user_id` = the sweeping operator (load-bearing for the later SoD check); the sweep skips the intake interval rules — `routes/meters.py:210-229`
- `§3.4` — insert — ambiguity — all four resolve-exception fields are required, but `resolution_note` alone may be empty/whitespace and is stored verbatim — `routes/meters.py:125-128`
- `§3.5` — insert — ambiguity — delivery to a `REMOVED` device reports `ERR_DEVICE_INVALID_STATE` (409), after the order's status gate — `routes/consumables.py:90-91`
- `§3.6` — insert — ambiguity — a parts-hold on a ticket with null `part_sku` also reports `ERR_PART_IS_AVAILABLE` — `routes/tickets.py:160-161`
- `§2.9` (item 19) — revise — mismatch — `PARTS_HOLD` requires the ticket to *name* a `part_sku`; the old wording ("row is missing") licensed a hold on a part-less ticket — `routes/tickets.py:160-165`
- `§3.8` — revise — ambiguity — `quarter_label` must match `YYYY-Qn`, n in 1..4; other shapes are `ERR_INVALID_REQUEST` caught **before** `contract_id` resolution — `routes/reviews.py:28-31`
- `§3.9` — revise — mismatch — collection's in-flight-ticket bar reports `ERR_REMOVAL_INVALID_STATE` (409), applies to every covered device regardless of `lifecycle_state`, and fires **before** `ERR_COLLECTION_NOT_DUE` — `routes/removals.py:108-115`
- `§3.9` — revise — mismatch — dropped the false "`SERVICE_HOLD` case additionally requiring..."; the bar is global, and a covered device outside the four fleet states is left untouched — `routes/removals.py:117-120`
- `§3.9` — insert — ambiguity — sanitization evidence: `<=120` chars; absent/`null`/`NONE` method and absent/`null`/empty/whitespace certificate => `ERR_SANITIZATION_EVIDENCE_MISSING`, while a bad enum member or an over-long certificate => `ERR_INVALID_REQUEST`; both after the `COLLECTED` gate — `routes/removals.py:131-140`
- `§3.9` — insert — ambiguity — settlement's non-`TERMINATING` contract reports `ERR_CONTRACT_INVALID_STATE` (409), before the period test — `routes/removals.py:158-161`
- `§4` (preamble) — revise — mismatch — the "creation => 201" universal was false twice: the meter sweep creates `MeterRead` rows but answers 200 with the `BillingPeriod`, and the locker adjustment answers 200 even when creating — `routes/meters.py:232-235`, `routes/sites.py:136`
- `§4` (device statement-lines row) — revise — mismatch — not "every line ever written": superseded provisional lines are deleted; ordering is creation order — `routes/devices.py:174-179`, `routes/billing.py:106-110`

## Verified clean (no change needed)
- **All 64 role sets** in the §4 table match their `require(...)` calls exactly — zero mismatches.
- **The §2.9 ladder holds at every endpoint.** Every route's check sequence is strictly ascending in ladder order, including the non-obvious ones: OCC before state before contract-active (`provisional-statement`, `consumable-orders`), state -> certification -> region -> window (`dispatch`), state -> ownership -> parts (`parts-hold`, `arrive-onsite`), state -> ownership -> labour ceiling (`resolve`), and contract-active before ownership (`POST /service-tickets`). The three newly-pinned codes all land at item 7, which correctly precedes items 22/29 they fire before.
- All 13 list-endpoint filter sets, the pagination/ordering rules, and every optional-input default match §2.3 / §3 as written.

## Integrity
466 lines, 122,459 chars; last heading `## 5. Error Code Catalogue` (line 406) with its table complete through `ERR_TONER_CAP_EXCEEDED`; 64 endpoint rows present; no duplicated or half-applied edit (verified by grep).

## Pipeline complete — 2026-09-04T09:02:00.000Z

All nine steps done. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`,
`SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files, 2301 lines), `test_suite/` (18 files,
11,055 lines, 239 collected cases), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md,
PRD_COMPLETED.md}`, `workspace/implementation/` (3,297 lines Python + Flask, 64 endpoints,
in-memory only) and the eight passing `results.{1..8}.json`.
