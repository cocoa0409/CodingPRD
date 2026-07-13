# Worklog — task_0820_community_garden_plot

Scenario: Community Garden & Plot Allocation: plot inventory & size, application & waitlist, seasonal fee & work-hour requirement, assignment & renewal priority, rule/abandonment compliance, water usage, shared tools/shed, forfeiture/reassignment

Difficulty: Expert

## Step 1: Create task directory — 2026-07-10T00:00:00.000Z

Created `tasks/task_0820_community_garden_plot/` and `tasks/task_0820_community_garden_plot/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate scaffold — 2026-07-10T13:57:00.000Z

All checks pass. The scaffold is complete and internally consistent.

## Summary

Generated three scaffold artifacts for **task_0820_community_garden_plot** (Expert difficulty) at `/home/ubuntu/github/CodingPRD/tasks/task_0820_community_garden_plot/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design` key

**`scaffold_lint.py` verdict: `clean lint`** — all 276 §1.8/§1.9 calls conform to §1.5, and all §1.1 FKs have reverse-reachability GETs.

### Counts
- **Entities:** 11 (Garden, Plot, Gardener, Application, Assignment, WorkLog, WaterReading, ComplianceCase, Tool, ToolLoan, ShedBooking)
- **State machines:** 5 (Plot cyclic; Application branching; Assignment parallel occupancy×fee axes; ComplianceCase branching; ToolLoan)
- **Calculations:** 6 (assignment_fee dual-variant/mode-a, water_overage_charge mode-b, renewal_priority_score dual-variant/selector, tool_late_fine, plus 2 named conserved-quantity invariants)
- **Validations:** 35 (priority-ordered; two priority-conflict pairs on distinct category pairs)
- **Endpoints:** 44 (flat topology, `api_prefix: ""`; includes `/_clock/set_current_utc` with default `2026-03-01T00:00:00Z`)
- **Errors:** 35
- **Roles:** 3 (Gardener entity_backed; GardenManager + Treasurer opaque, segregation-of-duties)
- **Concurrency rules:** 1 (OCC on Plot.version for `POST /plots/{id}/assign`)

### Design instances
- **Difficulty design:** 18 instances — exactly 2 per each of the 9 Difficulty Rules, all grounds resolve, all formula-derived asserts pre-computed as literals (fee 6000/7012/7245/4012/4000, water per-period-round 12-vs-11, priority 5/-3, fine 0/200).
- **Corner design:** 29 instances (26 active + 3 `excluded_because` stubs referencing valid §1.8 instances) spanning entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency_model.

No name collisions across the two design files; no forbidden concurrency vocabulary anywhere.

Note: two YAML flow-sequence fixes were applied post-authoring (quoting bare `?` optional tokens on `input:` lines and quoting bracketed `grounds:` items) — both are the known lint-safe fixes from prior batches.

Orchestrator verification: all three YAML files `yaml.safe_load` cleanly; SCAFFOLD.yaml has 44 endpoints.

## Step 3: Copy shared files — 2026-07-10T13:58:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0820_community_garden_plot/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T14:05:00.000Z

All 35 error IDs surface in the narrative prose. The PRD is complete and passes all three hard contracts.

## Summary

Generated `workspace/PRD.md`.

**Metrics:**
- **PRD line count:** 282 lines
- **Endpoints documented:** 44 / 44 (verified against §4 table)
- **Structure:** §1 Introduction, §2 (2.1–2.8 global specs incl. verbatim §2.2 envelope), §3 (3.1–3.9 business-logic scattering zone), §4 endpoint table (4 columns), §5 error catalogue (2 columns, 35 errors)

**Hard-contract checks (all PASS):**
- Contract 1 (Field-Name Coverage): 0 missing — every entity field, request-body key, query param, and path var (incl. `to_iso8601`, `expected_plot_version`, `amount_cents`, common fields `id`/`created_at`/`updated_at`/`version`) appears verbatim in backticks.
- Contract 2 (Rule Coverage): all state transitions, both dual-variant calculations (`assignment_fee` provisional/final, `renewal_priority_score` as_submitted/as_of_allocation), `water_overage_charge` (pinned round-per-period-then-sum), `tool_late_fine` (ceil-to-hour), the OCC rule (`expected_plot_version` → `ERR_STALE_VERSION` 412), validation priority ordering, and cascade side-effects (escalate→forfeit→auto-offer, ledger reconciliation) are expressed in precise prose. All 35 error IDs appear in narrative, not just the table.
- Contract 3 (§3 Path Purity): 0 violations — no HTTP methods or URL paths in §3 backticks.

**Scaffold gap found (reported per instructions):**
- **`CURE_GRACE_DAYS` is referenced but never assigned a value.** It is used in the state machine (`cure_deadline = clock + CURE_GRACE_DAYS`), the `ComplianceCase.cure_deadline` field description, and the warn-endpoint side effect, but it does not appear in any `calculations[].constants` block. I documented the rule by name ("current clock plus a fixed cure grace period (`CURE_GRACE_DAYS` days)") without inventing a value; the implementer/test-generator will need a concrete value that the scaffold does not supply.

No other undeclared constants — all fee, water, priority, and late-fine constants (`BASE_FEE_CENTS`, `WATER_DEPOSIT_CENTS`, `REQUIRED_WORK_HOURS`, `WORK_SHORTFALL_PENALTY_CENTS_PER_HOUR`, `WATER_FREE_GALLONS_PER_PERIOD`, `WATER_RATE_CENTS_PER_GALLON`, `SEASON_PERIODS`, priority weights/bonuses, `TOOL_LATE_FINE_CENTS_PER_HOUR`) have declared values and were embedded in business prose with unit context.

### Orchestrator patch (undeclared-constant repair, applied post-Step-4)

`SCAFFOLD_DIFFICULTY_DESIGN.yaml:294` pins WARN at 2026-03-15 → `cure_deadline` 2026-03-29, and `SCAFFOLD_CORNER_DESIGN.yaml:195` pins clock 2026-03-30 > deadline 2026-03-29 → `ERR_CURE_PERIOD_EXPIRED`. Therefore `CURE_GRACE_DAYS = 14`. Declared it in three places in `SCAFFOLD.yaml` (ComplianceCase.cure_deadline field description; WARN transition side_effect; warn-endpoint side_effects) and pinned it in `workspace/PRD.md` §3 warn paragraph ("a fixed cure grace period of exactly 14 days (`CURE_GRACE_DAYS` = 14)"). Scaffold re-validated with `yaml.safe_load` after the patch. PRD is 281 lines.

## Step 5: Generate unit tests — 2026-07-10T14:22:00.000Z

All citations verified verbatim. The full suite collects cleanly (62 tests). Everything is complete.

## Summary

Generated complete test infrastructure and suite for `task_0820_community_garden_plot`.

**Test infrastructure — `test_helpers/` (9 files):**
`__init__.py` (barrel), `types.py` (11 entity TypedDicts + 8 enums; append-only WorkLog/WaterReading/ShedBooking correctly omit `updated_at`/`version`), `api_client.py` (one method per endpoint), `api_errors.py` (35 error IDs + HTTP map registered with framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque manager/treasurer constants + entity-backed `make_gardener_headers` identity threading), and `fixtures.py` (primitives + 6 composite setups reused across both queues).

**Test suite — `test_suite/` (conftest + 6 domain files): 62 tests.**

**Queue A (Difficulty) coverage: 18/18 non-stub instances, 2 tests each = 36 tests.** All 9 rules × 2 instances translated (dual-variant fees & priority scoring, combinatorial final fee & water-rounding order, parallel occupancy/fee axes & compliance branching, forfeiture & abandonment cascades, two priority-pair conflicts, work-hour & tool-return boundaries, two cross-entity dependencies, tool-buffer & shed-adjacency overlaps, plot-pool & fee-ledger conservation). Boundary neighbors used for the second test where natural (11h→5500 penalty, return `due_at`+1s→200 fine, past-buffer/touching-boundary allowed cases).

**Queue B (Corner) coverage: 26/26 non-stub instances, 1 test each = 26 tests** (entities, state machines, calculations, validations, endpoints, rbac, cross-cutting OCC, consistency).

**Stubs (correctly NOT translated): 3** — `water_overage_rounding_order_delta`, `error_renewal_blocked_by_compliance_trigger`, `error_tool_time_conflict_trigger`. All three `excluded_because` cross-references resolve to real difficulty instances that own the assertion.

**Instances skipped for PRD-filter failure: 0.** One partial fidelity note: `garden_system_fields_generated_on_create` asserts only the PRD-covered roll-ups (`total_plots==0`, `available_plot_count==0`); its `version==1` sub-assertion was dropped because PRD §2.4 states version *increments on mutation* but never pins the initial value (not uniquely derivable). The instance remains covered.

Every test docstring carries verbatim PRD citations (spot-checked via literal `grep` of `workspace/PRD.md`) and exactly one `Design:` tag; no `skip`/`xfail` used. `pytest --collect-only` succeeds with all 62 tests importing cleanly against the installed `prd_bench_local_runner.testing` framework.

## Step 6: Generate implementation — 2026-07-10T14:22:00.000Z

All tests pass and the server boots cleanly over HTTP via `start.sh`, binds `0.0.0.0:$PORT`, returns the correct envelope, and enforces auth (401 without headers).

## Summary

Generated a complete Python + Flask in-memory implementation for task_0820_community_garden_plot.

**Files created** (all under `workspace/implementation/`):
- `app.py` — Flask app, response envelope, auth decorator, validation helpers, all 44 routes
- `store.py` — in-memory dicts, logical clock, constants, calculations, serializers
- `requirements.txt` — `flask>=2.0`
- `start.sh` — guarded-install foreground launcher (`exec python3 app.py`, reads `$PORT`, binds `0.0.0.0`)

**Verification:**
- `ast.parse` passes on all `.py` files
- `app.py` exists; **route count = 44** (matches scaffold; created Flask with `static_folder=None` so no extra static route)
- Smoke + edge tests pass: full allocate→settle→pay→refund flow, provisional/final fee math (per-period water-rounding, work-shortfall penalty, deposit credit, floor-at-zero), OCC stale-version (412), season conflict, compliance strike→standing→escalate cascade (forfeit + auto-offer), forfeit auto-offer to waitlist, offer-expiry sweep, tool late fine (ceil-hours), duplicate email/application/water-reading, list pagination envelope, and real HTTP boot.

**Storage:** in-memory dicts only; nothing seeded at startup; clock defaults to `2026-03-01T00:00:00Z`. `CURE_GRACE_DAYS = 14`.

**PRD ambiguities resolved by interpretation:**
1. **Validation ordering (ownership vs. existence).** The PRD lists authorization (priority 2, incl. gardener ownership) before existence (priority 3), but ownership on resource-scoped actions (accept/decline/request-renewal/work-logs) requires the resource to be loaded first. I check role-permission → existence → ownership. For actions where `gardener_id` is in the request body (tool-loans, shed-bookings), ownership is a pure header-vs-body compare done before existence, per the priority order. The only conflicting combination (nonexistent resource + wrong owner) is untestable.
2. **`version` initial value.** Not stated; I start every common-fields entity at `version = 1` on create, +1 per mutation. Plot offer→reserve makes version 2, etc.
3. **confirm-renewal return + plot pointer.** Endpoint is code 201 ("mints the next-season assignment"), so I return the newly created next-season assignment. The new assignment copies the garden's current season window (no separate "next season" data exists), adds its provisional fee to the ledger, and I repoint `plot.current_assignment_id` to it (plot stays `ASSIGNED`; no version bump since not specified).
4. **`api_request_timestamp`.** Rendered from the logical clock (deterministic) rather than wall-clock, consistent with §2.4.
5. **expire-offers response.** Returned as a bare `response_type: "array"` of expired applications without pagination meta (it is a sweep, not a paginated list endpoint).

Orchestrator verification: `ls` confirms app.py + store.py + start.sh + requirements.txt; `ast.parse` OK; `grep -c @app.route` = 44 (== scaffold endpoint count, no partial-write gap); test_suite has 62 tests across 6 files.

## Step 7: Run tests and iterate — 2026-07-10T14:35:00.000Z

The task is already fully passing. No fixes needed.

## Summary

- **Iterations run:** 1 (initial 8-round stability sweep).
- **Result:** All 8 rounds passed cleanly — 62/62 tests passed, 0 failed, 0 errors, 0 skipped in every round. No flakiness surfaced across the two waves of four.
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.

The implementation in `workspace/implementation/` (app.py + store.py) already satisfies the full test suite (`test_01` through `test_06`, 62 tests) with no timing-sensitive failures. The task was in a clean passing state on arrival; the diagnostic protocol was not triggered since no test failed in any round.

Orchestrator verification (independent of subagent claim): all 8 `results.{1..8}.json` exist and each reports `passed == total == 62`, `failed == 0`, `errors == 0`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-10T14:36:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond the baseline). `PRD.md` already uniquely determined every behavior the implementation exhibits at the sites the tests exercised. No `PRD_FINALIZED.md` produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-10T14:45:00.000Z

Done. All edits are complete and confined to `PRD_COMPLETED.md`.

## Summary

- **Source vs completed**: `PRD.md` = 281 lines / 41,549 chars → `PRD_COMPLETED.md` = 281 lines / 45,382 chars (char delta **+3,833**; all changes were in-paragraph inserts/revisions, no new lines or sections).
- **Counts**: 11 ambiguity-pins, 5 mismatch-revisions (16 total).

### Changes

- §2.2 (`api_request_timestamp`) — insert — ambiguity — pinned that the timestamp is rendered from the logical-clock instant, not host wall-clock — `app.py:40` / `store.py:32,60`.
- §2.3 (Pagination) — insert — ambiguity — pinned `id` ascending as the tiebreaker when `created_at` is identical — `app.py:196`.
- §2.4 (Versioning) — insert — ambiguity — pinned `version` begins at 1 on creation (`updated_at` == `created_at`) — `app.py:304,385,555` etc.
- §2.8 (Validation ordering) — revise — mismatch — PRD said ownership always precedes existence; pinned that ownership precedes existence only when `gardener_id` is in the body (application submit, tool-loan checkout, shed booking), but follows existence for resource-scoped actions (accept/decline, request-renewal, work-log, water-reading, tool-loan return) — `app.py:643-644,720-722,881-882,1101-1103,1162-1163`.
- §3.1 (Plots) — insert — ambiguity — pinned plots list filters `garden_id`, `status`, `size` — `app.py:397-410`.
- §3.3 (Offer ranking) — revise — mismatch — PRD said tie-break "never by `id`"; pinned `id` ascending as final tiebreaker (impl uses it) — `app.py:425-431`.
- §3.3 (Offer availability) — revise — mismatch — pinned that the `ERR_PLOT_NOT_AVAILABLE` check runs before candidate selection, and that `ERR_SIZE_MISMATCH` is unreachable on the offer path (candidates pre-filtered by size) — `app.py:487-491`.
- §3.3 (Offer response) — insert — ambiguity — pinned HTTP 200 returning the offered application — `app.py:493`.
- §3.3 (Accept ordering) — revise — mismatch — PRD checked expiry before the RESERVED/size pairing re-checks; pinned impl order (RESERVED → size → expiry) — `app.py:645-653`.
- §3.3 (Decline response) — insert — ambiguity — pinned HTTP 200 returning updated application, and that a missing/non-RESERVED plot skips release but still declines — `app.py:672-680`.
- §3.3 (Expire-offers response) — insert — ambiguity — pinned bare `array` envelope, sorted `created_at` then `id`, with no pagination meta and no windowing — `app.py:356-361`.
- §3.4 (Assignments) — insert — ambiguity — pinned assignments list filters (`plot_id`, `gardener_id`, `garden_id`, `application_id`, `renewed_from_assignment_id`, `occupancy_status`, `fee_status`) — `app.py:692-708`.
- §3.7 (Confirm-renewal) — insert — ambiguity — pinned: returns HTTP 201 with the new next-season assignment, copies the garden's current `season_start`/`season_end` (window not advanced), adds provisional fee to ledger, repoints `current_assignment_id`, plot stays `ASSIGNED` with no version bump — `app.py:735-756`.
- §3.8 (Escalate) — revise — mismatch — pinned that forfeiture cascade fires only when the linked assignment is still `ACTIVE`/`RENEWAL_PENDING`; otherwise case still moves to `ESCALATED` with no forfeiture — `app.py:1045-1047`.
- §3.9 (Tool-loan conflict) — insert — ambiguity — pinned boundary treatment (buffer-extended end exclusive; new `due_at` == existing `checked_out_at` conflicts) — `app.py:1119-1123`.
- §3.9 (Tool loans) — insert — ambiguity — pinned tool-loans list filters `tool_id`, `gardener_id`, `status` — `app.py:1148-1156`.

All five generator-self-reported interpretation choices were verified against the code and pinned (validation ordering §2.8; `version`=1 §2.4; confirm-renewal shape §3.7; `api_request_timestamp` logical clock §2.2; expire-offers bare array §3.3). Beyond those I found and pinned additional silences/mismatches: pagination/offer `id` tiebreak, offer availability-first ordering + unreachable `ERR_SIZE_MISMATCH`, accept re-check ordering, decline/offer return shapes, three list-filter enumerations, tool-loan overlap boundary, and the conditional escalation cascade.

Orchestrator verification: `PRD_COMPLETED.md` exists (281 lines, 45,382 chars); `PRD.md` unmodified at 281 lines / 41,549 chars; `PRD_FINALIZED.md` correctly absent (Step 8 skipped). Temporary `sweep.sh` removed.

---

## Pipeline complete

All 9 steps done. Final state: 62/62 tests passing across 8 independent stability rounds; 44/44 endpoints routed; PRD_COMPLETED.md is the ambiguity-free contract.
