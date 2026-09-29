# Worklog — task_2687_contact_center_workforce_management

## Step 1: Create task directory — 2026-09-04T06:42:22.561Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2687_contact_center_workforce_management` and its `workspace/` subdirectory. Index 2687 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-04T08:24:22.237Z

All three scaffold artifacts are complete, lint-clean and parse as valid YAML.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2687_contact_center_workforce_management/`

### SCAFFOLD.yaml — 3383 lines (167 KB)
`domain_name: contact-center-workforce-management`, `api_prefix: "/"`, logical clock default `2026-08-01T00:00:00Z`. Contains only §1.0–§1.7 (verified: no `scaffold_difficulty_design` / `scaffold_corner_design` keys).

- **15 entities**: PlanningCycle, LaborAgreement, ForecastGroup, MarketingEvent, IntervalPlan, Agent, ShiftTemplate, BidRound, ShiftBid, ScheduleShift, AdherenceException, IntradayAction, OutsourcePartner, PartnerAllocation, HiringClass
- **68 endpoints**, **53 error ids**, **32 validation rules** (priority 10 -> 205), **14 calculations**, **12 state machines**, **2 `concurrency_rules`** (`reforecast-stale-cycle` on PlanningCycle / `expected_cycle_version`; `allocation-commit-stale-partner` on OutsourcePartner / `expected_partner_version`), **8 roles** (CapacityPlanner, WorkforceAnalyst, SchedulingManager, IntradayController, Agent `entity_backed`, TeamCoach, SourcingManager, PartnerRep `entity_backed`)
- `complexity_profile`: temporal_windowing primary / quota_allocation secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology; parallel state-machine shape; immediate consistency
- Headline rules: Erlang-style staffing with SL-uplift bands vs occupancy cap (dual variant, `MAX_OF_BOTH`), confidence-weighted capped marketing-event uplift with AHT drag, exponential reforecast smoothing (alpha 0.4, clamp 0.5–2.0), seniority waterfall bid award with a preference-honour floor, cost-tiered overtime evaluated on pre-state spend, partner allocation waterfall with PROBATION capping at the commitment floor, per-line partner settlement (COMMITMENT_FLOOR vs DELIVERED_ONLY with 25% shortfall penalty), hiring-class ramp FTE at 0.5 nesting productivity

### SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1760 lines (121 KB)
Single top-level key `scaffold_difficulty_design`: **9 rule_ids / 21 instances** (all nine mandated rules, >=2 instances each) — dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

### SCAFFOLD_CORNER_DESIGN.yaml — 4637 lines (308 KB)
Single top-level key `scaffold_corner_design`: **9 sections / 81 instances** (69 with full `test_recipe`, 12 `excluded_because` stubs, every cited `difficulty_instance` resolving by name in §1.8):
entities 10, state_machines 13, calculations 14, validations 18, endpoints 6, errors 6, rbac 7, cross_cutting_complexity_layers 6, consistency_model 1. All `claim_type` values come from `references/claim-extraction-guide.md`; instance names are unique across the union of both design files.

### Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 68 endpoints, 15 entities, 21 §1.8 instances, 69 §1.9 instances, **936 calls scanned**, zero violations. (Two late `(d) capture JSONPath unresolvable` hits — `$.data.total_count` captured off list endpoints whose output is `PlanningCycle[]` — were fixed by dropping the captures and asserting `total_count` in prose, matching the file's existing list convention.)
- **Error coverage audit: 0 of 53 error ids un-asserted** — every catalogued error is now triggered by at least one §1.8 or §1.9 instance (the 15 entity-specific 404s land in one `errors` instance; ERR_UNAUTHENTICATED/UNAUTHORIZED/OWNERSHIP_VIOLATION/SEGREGATION_OF_DUTIES in `rbac`; both 412s in `cross_cutting_complexity_layers`).
- `yaml.safe_load` succeeds on all three files.

Orchestrator verification: all three files present in task root; workspace/ survived the scaffold step (no wipe this run).

## Step 3: Copy Shared Files — 2026-09-04T08:24:40.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T08:42:51.264Z

PRD generation complete and verified.

### Output
`workspace/PRD.md` — **456 lines**, 112 KB, built with 8 chunked `cat >>` appends plus targeted `Edit` fixes. Never read `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

### Section list
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version Counters, 2.5 The Logical Clock, 2.6 Numeric Precision/Rounding/Units, 2.7 Optimistic Concurrency Control, 2.8 Planning-Cycle Posture as a System-Wide Gate, 2.9 Cascade Discipline, 2.10 Request Validation Order
- §3 Business Logic & Workflows — 3.1 Planning Week & Labour Envelope, 3.2 Forecasting Demand & Staffing Requirement, 3.3 Marketing Drivers & Uplift Cascade, 3.4 Roster & Hiring Pipeline, 3.5 Shift Templates/Bid Rounds/Award Waterfall, 3.6 Publishing Under Labour-Agreement Ceilings, 3.7 Intraday Management, 3.8 Adherence/Coaching/Exception Adjudication, 3.9 Partner Allocation/Commitment/Settlement
- §4 API Endpoints — 68 rows, 4 columns
- §5 Error Codes — 53 rows, 2 columns

### Coverage (machine-verified against SCAFFOLD.yaml)
- **Endpoints 68/68** — §4 table has exactly 68 data rows; method, path and exhaustive role list taken programmatically from the scaffold.
- **Entities 15/15** — all described in prose; **Contract 1: 184/184 required identifiers (194 entity fields plus all request-body/path/query identifiers) appear verbatim in standalone backticks — 0 missing.**
- **Validations 32/32** — every priority band narrated; §2.10 spells out the full ladder from authentication through the two fiscal checks.
- **Calculations 14/14** — all narrated in prose with no operators or pseudocode (dual variants of `staffing_requirement` and `partner_settlement` both shown as divergent on identical data).
- **State machines 12/12** — every declared `from`/`to` state present in backticks (the two independent `ScheduleShift` axes documented as an explicitly non-interacting pair).
- **Errors 53/53** — all ids appear in prose and in §5 with matching HTTP statuses.
- **Roles 8/8** — all present, including both entity-backed roles and their ownership scopes.
- **Concurrency rules 2/2** — `expected_cycle_version`/`ERR_STALE_CYCLE_VERSION` on reforecast and `expected_partner_version`/`ERR_STALE_PARTNER_VERSION` on allocation commit.
- **Contract 3 (§3 path purity): 0 violations** — of 356 backtick tokens in §3, none starts with `/`, none is a bare HTTP method, none contains a slash.
- **§2.2** diffs byte-identical against `section-2.2-response-structure.md`.
- No fuzzy hedges and no scaffold-internal leakage (`calculations.`, `concurrency_rules`, `applies_to`, `test_recipe`, `§1.x` all absent).

### Two defects caught and fixed during verification
1. §4's intro invented two error ids that do not exist in the scaffold (`ERR_ROLE_NOT_PERMITTED`, `ERR_MISSING_ROLE`); corrected to `ERR_UNAUTHORIZED` (403) and `ERR_UNAUTHENTICATED` (401).
2. Five path-parameter identifiers (`shift_bid_id`, `adherence_exception_id`, `intraday_action_id`, `partner_allocation_id`, `marketing_event_id`) and the `INFO_REQUESTED` state existed only inside compound backtick spans; each now has a standalone backticked mention in §3.

Note from the subagent: its first Contract 1 pass reported a false 165-token failure. Cause was the checker, not the PRD — a naive backtick-pairing regex mispairs across the triple-backtick JSON fences in §2.2. Any future audit of this file must use substring matching on the quoted token rather than global backtick pairing.

### Not truncated — verbatim last 3 lines
```
| `ERR_PARTNER_VOLUME_OUT_OF_RANGE` | 422 |
| `ERR_OT_BUDGET_EXCEEDED` | 402 |
| `ERR_COMMITMENT_FLOOR_BREACH` | 409 |
```

Orchestrator anti-truncation check (per the caller's explicit warning): independently re-read the tail — the file ends on the completed §5 error table, not mid-sentence. Independent row counts confirm 68 endpoint rows and 53 `ERR_` rows. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T09:23:21.930Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's physical-isolation requirement. Step 6 finished first; its summary is recorded here, Step 5's below.)

Implementation complete. All 68 endpoints are live, the suite compiles cleanly, and an end-to-end smoke run through every subsystem passed.

### Files written (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `core.py` | 641 | 53-entry error catalog + `ApiError`/`fail`, RBAC (`require_auth`), Decimal helpers, logical clock, in-memory store (15 dict tables), response envelope, pagination, ~20 `v_*` body validators |
| `cascade.py` | 525 | `set_fields`/version coalescing, `cycle_of_row` frozen-gate resolution, the interval recompute chains, cycle/agent/template rollups, `mint_shift`, the 4 labour-safety predicates |
| `routes_partners.py` | 347 | 11 endpoints |
| `routes_roster.py` | 340 | 12 endpoints |
| `routes_bidding.py` | 330 | 9 endpoints |
| `routes_demand.py` | 320 | 11 endpoints |
| `calc.py` | 289 | all 14 named calculations + global constants |
| `routes_intraday.py` | 287 | 5 endpoints |
| `routes_shifts.py` | 284 | 10 endpoints |
| `routes_planning.py` | 252 | 10 endpoints (incl. `/_clock/set_current_utc`) |
| `app.py` | 64 | Flask app, 7 blueprints, `ApiError`/HTTPException handlers, `0.0.0.0:$PORT` (default 10000) |
| `listing.py` | 27 | shared list/filter/pagination wrapper |
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

**Endpoint count: 68 — verified by diffing the Flask url_map against the PRD §4 table programmatically: 0 missing, 0 extra.**

### Organisation
- **14 calculations** all live in `calc.py` (uplift -> volume -> AHT -> both staffing variants -> coverage -> internal capacity -> partner settlement -> OT tiering -> shift adherence -> partner rolling performance -> hiring ramp); `cascade.py` is the only place that sequences them, so the transitive chain (uplift -> ... -> `coverage_state` -> `cycle.short_interval_count` -> posture) exists once.
- **12 state machines** live with their entity's routes: cycle posture + system posture edges (`routes_planning.py`/`cascade.evaluate_posture_edges`), marketing event (`routes_demand.py`), agent employment + hiring class (`routes_roster.py`), bid round + bid incl. the `AWARDED->OPEN` reopen cascade (`routes_bidding.py`), the two parallel shift axes + adherence exception (`routes_shifts.py`), intraday action (`routes_intraday.py`), partner ladder + allocation (`routes_partners.py`).
- **32 validations** are enforced as a fixed band order in every handler: auth 10 -> role 20 -> body shape 25 -> pagination 28 -> path FK 30 -> body FK 40 (entity declaration order) -> ownership 50 -> SoD 60 -> OCC 65 -> frozen 70 -> own-state 80 -> posture 90 -> business 100–205 exactly as PRD §2.10 enumerates.
- **53 errors** are a single `ERROR_HTTP` map in `core.py` driving both `ApiError.http_status` and the `response_type: "error"` envelope.

### Smoke-test evidence (port 21687, then a fresh boot on 21688; only its own PIDs killed)
- `POST /planning-cycles` -> 201, `GET` -> 200, envelope exactly `meta{api_request_id: req_+20, api_request_timestamp}` / `response_type` / `data`; list responses add `limit/offset/total_count/has_more`.
- Calculation-bearing: `POST /forecast-groups/{id}/interval-plans` -> 201 array, `volume_forecast 1440`, `required_service_level 210`, `required_occupancy_capped 202`, `required_agents 210` (MAX_OF_BOTH), `coverage_state SHORT`; coverage-summary aggregated 350/2400.
- Full chain verified: bid round OPEN->SCORING->award (honor rate 1.0, 2 shifts minted) -> publish (paid_hours 7.5, agent 7.5, cycle 7.5) -> observation 0.6667/OUT_OF_ADHERENCE + `flagged_by_user_id` -> SoD 403 for the flagging user, approve by another coach -> EXCUSED 0.963, coaching `CLEARED` -> OT accept `cost_cents 3000`, `ot_multiplier_applied 1.5`, revoke restores ledgers to 0/0/7.5 exactly -> partner settle (2500 / 1875 / 156 / 1719, invoice 1719) -> performance ladder ACTIVE->PROBATION->SUSPENDED -> hiring ramp 8 graduates, `enrolled_agent_count` 10 -> reforecast OCC 412 then 200 with multiplier 1.0444 -> FROZEN then `ERR_CYCLE_FROZEN` 409. Also 401 unauthenticated, 400 `ERR_INVALID_PAGINATION`, 409 `ERR_DUPLICATE_BID`.
- `python3 -m compileall -q .` -> **0 syntax errors**. Fresh restart returned `total_count: 0` for cycles and agents, confirming zero seeding and full state wipe per `start.sh` invocation; no sqlite/file/`/tmp` persistence anywhere in the sources.

Orchestrator note: verified no stray `workspace/test_helpers/` or `workspace/test_suite/` directories exist (a known misplacement failure mode) — both test directories are correctly at the task root.

## Step 5: Generate Unit Tests — 2026-09-04T10:52:00.000Z

### Orchestrator note on how this step ran (deviation from the single-subagent shape, and why)

The Step 5 subagent was killed **twice** by upstream API errors ("The system encountered an unexpected error during processing"), first mid-way through writing `test_helpers/` and again after 8 test files. Both times its partial work was intact on disk, so per the established recovery rule I **resumed the same agent** (SendMessage with a computed to-do list derived from the on-disk state) rather than respawning a fresh one — a fresh agent would have rewritten the finished helpers and made the suite inconsistent with itself.

After the second death, queue A stood at 14/21 and queue B at 0/69, so the orchestrator made an autonomy call: keep the original agent on the **queue A remainder** (it held the domain/fixture mental model) and **fan queue B out across three fresh agents partitioned by §1.9 section**, with strictly disjoint output filenames. This was safe because `test_helpers/` was complete by then, so it could be declared FROZEN/read-only for all four agents; each was told to define any missing helper locally inside its own test file rather than touch a shared one. No agent was permitted to edit `conftest.py` or another agent's file. Result: zero write collisions, and the remaining ~76 instances finished in three concurrent slices instead of one serial one.

Partitioning:
- resumed original agent -> queue A remainder (7 instances) -> `test_08` (finished), `test_09`, `test_10`
- agent B1 -> `entities` + `state_machines` -> `test_20`, `test_21`
- agent B2 -> `calculations` + `validations` -> `test_30`, `test_31`
- agent B3 -> `endpoints` + `errors` + `rbac` + `cross_cutting_complexity_layers` + `consistency_model` -> `test_40`..`test_43`

### Final artifact

`test_helpers/` (9 files, 3105 lines): `__init__.py` 59, `api_client.py` 435, `api_errors.py` 156, `assertions.py` 434, `constants.py` 226, `factories.py` 502, `fixtures.py` 877, `test_users.py` 146, `types.py` 270. No extra helper file was needed by any of the four agents.

`test_suite/` (16 files, 7280 lines, **151 tests**): conftest 95, test_01 216, test_02 224, test_03 318, test_04 267, test_05 294, test_06 186, test_07 318, test_08 325, test_09 358, test_10 245, test_20 500, test_21 563, test_30 718, test_31 940, test_40 432, test_41 418, test_42 498, test_43 365.

Both directories are at the TASK ROOT; verified no stray `workspace/test_helpers/` or `workspace/test_suite/`.

### Orchestrator-verified coverage (independent script over both design YAMLs vs the `Design:` tags on disk)
- **Queue A (§1.8): 21/21 non-stub instances translated, 0 skipped.**
- **Queue B (§1.9): 68/69 non-stub instances translated, 1 skipped.**
- **151 tests, 151 `Design:` tags — exactly one per test, zero untagged, zero dual-tagged, zero orphan tags** (every tag resolves to a real non-stub instance).
- `python3 -m compileall -q test_suite test_helpers` -> zero syntax errors.

### The one skipped instance (PRD-first two-condition filter)
`Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_only_on_writes` — not uniquely derivable. Its `cyc_v_after_actuals == 1` contradicts PRD §2.9 ("Any operation that changes a row — whether the client addressed that row directly or a cascade reached it — ... increments that row's `version` by 1") combined with §3.7 (posting actuals recomputes the cycle's `short_interval_count`). Two faithful PRD readers diverge on whether the cascade bumps the cycle version, so the instance is a genuine PRD gap and stays a gap.

### Sub-assertion narrowings reported by the generators (instance core rule kept in each case; no instance weakened to pass)
- `latest_sl_attainment_pcts == [0.8000, 0.7000]` dropped — PRD says only that the pair "is appended ... in call order", leaving element shape (bare float vs object) ambiguous; replaced with a shape-agnostic length check plus `performance_report_count == 2`.
- `headcount_active == 0` at the draft-shift stage dropped — §3.4 counts a DRAFT shift toward `headcount_active` while the §3.4/§3.6 recompute triggers never include shift creation; kept `total_scheduled_hours == 0.00`, definitionally a sum over PUBLISHED shifts.
- `rbac/partner_rep_cannot_read_another_partners_allocations` narrowed — dropped the two sub-assertions that another partner's single-resource `GET /partner-allocations/{id}` and `GET /outsource-partners/{id}` return 403: §2.1 says ownership enforcement "is concrete and narrow" and enumerates six scopes, of which the only PartnerRep scope is *listing* allocations, and §4 authorizes PartnerRep on both single reads with no scoping sentence. Kept the list-filter breach (403) plus the rep's own successful reads.
- `endpoints/interval_grid_generation_is_all_or_nothing` — asserts `response_type == "array"` (PRD §2.2 wording) rather than the yaml's `"list"`, and drops the yaml's shared-`created_at` claim which PRD does not derive.
- `test_43` absolute cycle-version literals (`cyc_v2 == 2`, `v_body == 3`) replaced with values read from the API plus PRD-derived deltas (`locked_version`, `locked_version + 1`) — same unresolved cascade-versioning ambiguity as the skip above. The PRD-explicit increments (reforecast +1 version and +1 generation; each performance report +1; each commit +1) are still asserted exactly.
- `temporal_window_sanity_violations_rejected` — the design asserts `ERR_EVENT_WINDOW_INVALID` for a create whose `window_end == window_start`, but PRD §3.3 states the constraint without uniquely assigning that error id at create time (field-shape refusals are `ERR_VALIDATION`, also 422). Used the path PRD assigns verbatim instead: `CONFIRMED -> REALIZED` requested before the clock reaches `window_end` -> `ERR_EVENT_WINDOW_INVALID` (422). Knock-on: the marketing-events `total_count 0` sub-assertion became "event stays `CONFIRMED`", and the three horizon refusals plus the cycle-version-unchanged check were ordered before the event work so no confirm-driven recompute pollutes them.

### Two design-file bugs the generators caught and corrected
- `partner_committed_volume_counts_committed_and_settled_only`: `pen == 16` contradicts its own parenthetical and the sibling `amt == 469`; asserted 31/469 per PRD §3.9.
- Assignment-count drift: the `calculations` section holds 11 non-stub instances (+3 `excluded_because`), not the 12 the orchestrator's brief stated. Nothing was dropped for PRD reasons.

All `excluded_because` stubs (12 across both files) were correctly not translated.

## Step 7: Run Tests and Iterate — 2026-09-04T10:44:30.000Z

All 8 rounds pass 151/151. Done.

**Iterations run:** 2 (baseline sweep 143/151 in all 8 rounds; second sweep 151/151 in all 8 rounds). Failures were perfectly reproducible across all 8 parallel rounds — no flakiness or load-induced noise.

**Tests deleted:** none. All 8 failing tests traced to verbatim PRD prose; every failure was either a test-artifact bug (STEP 2) or a genuine implementation precedence bug (STEP 3).

### Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — `assert_shift_hours()` compared `end_at` by exact string, so `2026-09-07T16:00:00.000Z` failed against `2026-09-07T16:00:00Z`. PRD mandates three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`; it is silent on the serialization of `start_at`/`end_at`/`interval_start`. Switched to the suite's own `assert_instant_equals()` (whose docstring exists precisely to make fractional seconds not matter) — the exact instant is still pinned. Fixed 2 tests (`TestOfferExpiry`, `TestVoluntaryTimeOffAcceptance`).

### Fixes applied to `test_suite/`
- `test_40_corner_endpoints.py` / `TestIntervalGridBulkWrite` — same uncovered-serialization issue on `interval_start` / `interval_end`; replaced the three exact string equalities with `assert_instant_equals`.
- `test_21_corner_state_machines.py` / `test_locking_requirements_stamps_the_logical_clock_and_bumps_the_version` — captured `version_before` at cycle creation, then ran `generate_grid`, which per PRD 3.2 recomputes the cycle's `short_interval_count` (0 -> 4). Per PRD 2.4/2.9 a cascade that mutates a row increments that row's `version`, so the cycle was legitimately at 2 before the lock and 3 after. Now re-reads the cycle immediately before the lock so the assertion isolates the lock edge's own `+1` — the rule the cited sentence actually states.
- `test_31_corner_validations.py` / `test_an_overlapping_second_shift_is_refused_on_overlap_not_on_rest` — setup minted both same-day drafts before publishing the first. PRD's overlap rule bars any *other non-cancelled* shift, and DRAFT is non-cancelled, so the PRD-faithful server correctly refused the **setup's** publication. Reordered: publish the morning shift, then mint the colliding afternoon draft.
- `test_31_corner_validations.py` / `test_a_third_adjacent_day_breaks_the_consecutive_days_run` — same class of bug: all three Mon/Tue/Wed drafts were minted up front, putting the non-cancelled run at 3 against a `max_consecutive_days=2` ceiling before any publication. Reordered to mint-then-publish day by day, so the ceiling trips on the Wednesday attempt as intended.

### Fixes applied to `implementation/`
- `workspace/implementation/routes_shifts.py` / `drive_publication()` — the skill-eligibility check ran ahead of the four labour-agreement ceilings, so a shift breaching both rest and skill reported `ERR_SKILL_MISMATCH`. PRD 2.10 fixes the business-rule band order verbatim: "Then the four labour-safety checks against an agent's schedule, in this order: minimum rest ... Then skill eligibility (`ERR_SKILL_MISMATCH`)". Moved the skill check after `check_consecutive_days`. Fixed both `TestMinimumRestBeatsSkillMismatch` tests. (Section 3.6 merely enumerates seven preconditions without asserting cross-band order; 2.10 is the dedicated, self-described exhaustive precedence.)

**Final sweep evidence** — all 8 rounds `151/151` (0 failed, 0 errors, 0 skipped, ~270s each): `workspace/implementation/results.1.json` ... `results.8.json`

Orchestrator verification: independently parsed all 8 `results.$i.json` — every round reports `passed 151 / total 151`. Test count on disk is unchanged at 151, consistent with "0 deletions".

## Step 8: Finalize PRD — 2026-09-04T10:41:00.000Z

Step 8 was NOT skipped: Step 7 ran 2 iterations with 1 `implementation/` fix, 1 `test_helpers/` fix and 4 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) did not hold.

Done. Three edits, each traced to a `<step_7_diff>` item.

**Line counts:** PRD.md 456 lines / 114,784 B -> PRD_FINALIZED.md 458 lines / 116,780 B (+2 lines, +0.44% lines; +1.74% bytes).

### Changes
- **§2.4 (Resource Identity, Timestamps and Version Counters)** — *insert* — pins the serialization of every non-`created_at`/`updated_at` instant field: server-derived instants (`interval_start`, `interval_end`, `start_at`, `end_at`, `requirements_locked_at`, `published_at`) render with exactly three fractional digits and a trailing `Z`; client-supplied instants (`window_start`, `window_end`, `expires_at`, a routing adjustment's `interval_start`, and `current_utc`/`previous_utc`) are stored and echoed **verbatim**, the parsed value being used only for comparison — `core.py:190` (`iso3`), `core.py:576-586` (`v_datetime`), `routes_demand.py:127-128`, `cascade.py:351,492-493`, `routes_planning.py:32-36,116,129`, `routes_intraday.py:121-122`, `routes_demand.py:212-213`.
- **§2.9 (Cascade Discipline, third habit)** — *revise* — pins version/`updated_at` accounting as **per request, not per write**: one request advances a given row by exactly 1 total no matter how many times it reaches the row; a row created by the request counts creation as its first touch (so a freshly minted row whose derived fields are filled later in the same request still reads `version` 1 with `updated_at == created_at`); a recompute landing on the existing value moves nothing on its own, except where the document explicitly names an operation as incrementing a row's `version` — `cascade.py:15-32` (`set_fields`), `core.py:324-333` (`touch`, "at most once per row per request"), `core.py:306-315` (`new_row`).
- **§3.6 (Publishing the Schedule)** — *revise* — reordered the seven publication preconditions so skill eligibility is tested **after** all four labour-agreement ceilings, and stated that a shift breaching both reports the ceiling. Still "seven preconditions"; §2.10's band order was already correct and is left verbatim — `routes_shifts.py:88-97`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)
**Edit 1 — §3.6 ordering.** (a) Subject: precedence of `ERR_SKILL_MISMATCH` relative to the four labour-safety ceilings, and the publication precondition sequence. (b) Enumerated: `grep -rn ERR_SKILL_MISMATCH` -> `routes_shifts.py:96` (publication, the Step 7 site), `routes_intraday.py:98-100` (OT-offer **creation**: target group's skill vs agent's skills, no ceilings), `routes_bidding.py:283` (bid submission), `core.py:63` (status map); `grep -rn check_min_rest|check_overlap|check_weekly_hours|check_consecutive_days` -> `routes_shifts.py:88-94` and `routes_intraday.py:196-201` (OT acceptance runs rest->overlap->weekly only, no skill check, no consecutive-days); also read `routes_shifts.py:30-46` (manual create checks only horizon). (c) Adjustment: scoped the new sentence explicitly to the publication move instead of a global "skill always comes last" claim, so the OT-offer-creation and bid-submission skill checks and the three-rule OT-acceptance band in §3.7 are untouched.

**Edit 2 — §2.4 instant serialization.** (a) Subject: on-the-wire format of every instant-valued field. (b) Enumerated: `core.py:190-203` (`iso3`, `now_iso`, `wall_iso`), `core.py:366-379` (`json_safe`, `public()`), `core.py:308/331`, `core.py:576-586` (`v_datetime` returns the raw string unmodified), `core.py:180` (default clock raw `2026-08-01T00:00:00Z`, zero fractional digits, echoed as `previous_utc`), plus every write site: `routes_demand.py:127-128,212-213`, `cascade.py:351,492-493`, `routes_planning.py:32-36,116,129`, `routes_intraday.py:58,87,121-122`, and `iso_date` (`core.py:254`, not claimed). (c) Adjustments: put `current_utc`/`previous_utc` in the *verbatim* bucket rather than the three-digit bucket (§2.5's literal `2026-08-01T00:00:00Z` would otherwise be contradicted); said nothing about `effective_from_interval_start` (parsed but never stored or returned); confined the claim to instant fields so `service_date`, `start_date`, `period_end_date` keep plain-date rendering.

**Edit 3 — §2.9 version accounting.** (a) Subject: how many times one request may advance a row's `version`/`updated_at`. (b) Enumerated: `grep -rn "touch(|touched()"` -> `cascade.py:31` (the only generic bump, gated on an actual value change), `cascade.py:352` (`move_shift_end` then `recompute_shift_hours` re-entering `set_fields` as a no-op), `core.py:314` (`new_row` seeds `touched()`), `core.py:324-333` (`touch` early-returns on repeat), and the two *forced* bumps `routes_partners.py:140` (performance report) and `routes_partners.py:296` (allocation commit). Also traced multi-write requests: `routes_planning.py:116` + `cascade.py:203-219`, `routes_demand.py:119-156`, `routes_intraday.py:112-131`, `cascade.py:480-510` (`mint_shift`), and graduation's agent minting. (c) Adjustments: added the escape clause "except where this document explicitly states that a named operation increments a particular row's `version`" so the two forced `touch(partner)` calls (mandated verbatim by §3.9) are not contradicted; phrased the coalescing as "advances by exactly 1 in total, never once per touch" rather than naming specific cascades.

## Step 9 (pass 1 of 3): Complete PRD — core.py / calc.py / app.py / listing.py — 2026-09-04T10:56:00.000Z

Orchestrator decision: Step 9's full PRD-vs-implementation scan was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than a single subagent pass. A 12-module, 3400-line implementation reliably under-scans in one pass (the known failure signature is a `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never really ran). Pass 1 owns the initial `cp`; passes 2 and 3 were explicitly forbidden from copying, so they could not clobber earlier edits. Passes ran strictly sequentially because they all edit the same file.

Partition: pass 1 = `core.py`, `calc.py`, `app.py`, `listing.py`; pass 2 = `cascade.py`, `routes_planning.py`, `routes_demand.py`, `routes_roster.py`; pass 3 = `routes_shifts.py`, `routes_bidding.py`, `routes_intraday.py`, `routes_partners.py`.

### Pass 1 result
- `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed as the first action (source 458 lines / 116,780 chars).
- After edits: **458 lines, 121,757 chars** (line count unchanged — every edit is an in-paragraph insert/revision).
- **Ambiguity-pins: 12. Mismatch-revisions: 0.** The whole 54-entry error catalog was verified programmatically against the §5 table (identical ids, statuses, order), and all 14 calculations plus every global constant in `calc.py` against §3.2/3.3/3.5/3.7/3.8/3.9 formula prose, with no divergence.

Changes:
- §2.1 — insert — ambiguity — an auth header present but empty counts as absent (-> `ERR_UNAUTHENTICATED`) — `core.py:118-121`
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `core.py:359-363`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the host wall clock, not the logical clock, so it advances while the logical clock stands still — `core.py:201-203, 383`
- §2.3 — insert — ambiguity — `created_at` ties (routine, since the logical clock is frozen between operator sets) are broken by insertion order; that is what makes paging stable — `core.py:301-303, 349`
- §2.3 — insert — ambiguity — filters are conjunctive and string-compared against the stored scalar (the two array skill filters test verbatim membership); a null/empty filtered field never matches; an empty-string filter and any undeclared query param are ignored — `listing.py:9-27`, `core.py:637-641`
- §2.4 — insert — ambiguity — exact accepted syntax for client-supplied instants (space for `T`, optional seconds/fraction, >6 fractional digits ignored, `Z` / `±HH:MM` / `±HHMM` / no zone read as UTC), and calendar dates restricted to the 10-char form — `core.py:206-247, 576-586`
- §2.6 — insert — ambiguity — the 4-dp/2-dp scales govern stored values, not wire width: all are plain JSON numbers, so `1.0000` serialises as `1.0` and `0.00` as `0.0` — `core.py:366-370`
- §2.10 — insert — ambiguity — body-shape conventions: absent/empty/`null` body reads as `{}`; non-object or unparseable body is `ERR_VALIDATION`; undeclared fields ignored; explicit `null` treated exactly as absent (required->missing, optional->default, forbidden->passes); booleans never accepted for int/number — `core.py:462-474, 481-482, 508, 524, 600-602`
- §3.2 — insert — ambiguity — the single skill-code lexeme (`^[A-Z0-9]+(?:_[A-Z0-9]+)*$`) declared once and scoped to every skill field, compared case-sensitively — `core.py:605-617`
- §3.8 — insert — ambiguity — a shift with `scheduled_seconds` of zero scores `0.0000` (deliberately opposite to the agent rollup's `1.0000` empty-set convention, which lives in `cascade.py`) — `calc.py:236-239`
- §4 intro — insert — ambiguity — trailing slash tolerated on every path; the two batch-creating endpoints return 201 with `response_type` `array` and no pagination meta — `app.py:24`, `core.py:382-404`
- §5 intro — insert — ambiguity — the three off-catalogue transport identifiers `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), plus framework-level 400/415 folding into `ERR_VALIDATION` (422); also corrected a stale cross-reference "Section 2.6" -> "Section 2.10" — `app.py:37-49`

Hand-off pass 1 left for pass 2: §2.9's "a recompute that lands on the value the row already carried is not a change" was deliberately untouched, because `core.py:324-333`'s `touch()` is unconditional and the claim's truth is decided by the `set_fields`/recompute callers in `cascade.py` (pass 2's partition).

## Step 9 (pass 2 of 3): Complete PRD — cascade.py / routes_planning.py / routes_demand.py / routes_roster.py — 2026-09-04T11:10:00.000Z

`PRD_COMPLETED.md` before 458 lines / 121,757 chars -> after **458 lines / 127,712 chars** (+5,955). No sections added; every change in-paragraph. All 12 pass-1 markers verified individually still present exactly once. **3 mismatch-revisions, 17 ambiguity-pins.**

- §2.9 — revise — ambiguity — generalized "a recompute that lands on the value the row already carried" to *any* field assignment (recompute, cascade rollup or client-supplied replacement alike), compared against the stored value first, numeric fields by numeric value rather than decimal scale; a request in which no field moved leaves `updated_at` and `version` untouched — `cascade.py:15-32`
- §2.8 — insert — ambiguity — the cycle-independent registries (labour agreements, agents, partner records as distinct from their allocations) are never reached by the frozen gate — `routes_roster.py:53-138`, `routes_planning.py:216-240`
- §3.1 — insert — ambiguity — `target_posture` accepts all five posture names incl. `INTRADAY_ALERT`, refused with `ERR_INVALID_STATE` (409) not a validation failure; the two positive preconditions also `ERR_INVALID_STATE`; only the reverse-to-`OPEN` precondition has its own identifier (`ERR_CYCLE_NOT_OPEN`) — `routes_planning.py:105-131`
- §3.1 — insert — ambiguity — `REQUIREMENTS_LOCKED -> SCHEDULE_PUBLISHED` does not itself recompute `short_interval_count`, so a cycle can enter `SCHEDULE_PUBLISHED` already at/above threshold and stay there until the next perturbation — `routes_planning.py:124-129`
- §3.1 — insert — ambiguity — labour-agreement `code` collision is `ERR_VALIDATION` — `routes_planning.py:228-229`
- §3.2 — insert — ambiguity — the two operating-minute multiple tests and the `intraday_curve` length test run only after `planning_cycle_id` resolves, so `ERR_PLANNING_CYCLE_NOT_FOUND` wins — `routes_demand.py:54-61`
- §3.2 — revise — ambiguity — coverage counting consults no cycle (any published shift qualifies on skill + span, even from another cycle), and a coverage move recomputes `short_interval_count`/posture edges on every cycle owning a touched interval; routing contribution matches on exact `interval_start` equality, never overlap — `cascade.py:100-128, 356-378`
- §3.2 — revise — ambiguity — coverage-summary `service_date` narrows `interval_count` and the six sums but `short_interval_count` is read off the cycle row; the rollup ignores `limit`/`offset` — `routes_planning.py:189-210`
- §3.3 — insert — ambiguity — a marketing event's `forecast_group_id` is existence-checked only, not for cycle membership; a driver on a foreign cycle's group confirms cleanly and perturbs nothing — `routes_demand.py:197-198, 164-176`
- §3.4 — insert — ambiguity — `employee_code` collision is `ERR_VALIDATION`, tested before `labor_agreement_id` resolves — `routes_roster.py:64-66`
- §3.4 — revise — **mismatch** — the agent status-change headcount recompute set includes the cycle of the agent's own `hiring_class_id`, not only cycles where they hold a DRAFT/PUBLISHED shift; TERMINATED live-shift breach is `ERR_INVALID_STATE`; a PATCH supplying nothing (or only identical values) is a 200 no-op leaving `updated_at`/`version` alone — `routes_roster.py:104-138`
- §3.4 — insert — ambiguity — `cohort_name` collision is `ERR_VALIDATION`, tested before either FK — `routes_roster.py:232-235`
- §3.4 — revise — **mismatch** — `graduated_agent_count` is stamped once at graduation, not a live count of agents pointing back at the class — `routes_roster.py:336`
- §3.4 — insert — ambiguity — graduates get `full_name` equal to their generated code and `seniority_rank` 1 (whole cohort ties on seniority), plus the standard derived zeros — `routes_roster.py:319-335`
- §3.5 — insert — ambiguity — shift-template `code` collision is `ERR_VALIDATION`, after cycle resolution but ahead of the frozen gate — `routes_roster.py:165-169`
- §3.6 — insert — ambiguity — the rest rule's neighbour set is every other non-`CANCELLED` shift of the agent (DRAFT constrains like PUBLISHED), bounded by neither cycle nor week — `cascade.py:388-408`
- §3.7 — insert — ambiguity — `actual_volume`/`actual_aht_seconds` are integers >= 0, unbounded above; a repeat posting replaces both and re-derives the ratio against the then-current `volume_forecast` — `routes_demand.py:303-318`
- §3.7 — revise — ambiguity — reforecast `forecast_group_id` is existence-only; horizon containment for an instant is the half-open span from midnight UTC on `horizon_start_date` to midnight UTC on the day after `horizon_end_date` — `routes_planning.py:143, 182-186`
- §3.8 — insert — ambiguity — the agent-level pooled `adherence_pct` is **not** clamped and can read below 0.0000 — `cascade.py:283-302`
- §4 — revise — **mismatch** — the GET `/agents` table row now names the held-skill filter — `routes_roster.py:92-101`

**§2.9 hand-off verdict: the claim HOLDS, and pass 2 generalized rather than weakened it.** `cascade.py:15-32`'s `set_fields` is the single writer for every recompute and nearly every client write; it compares each incoming value against the stored one (`D(old) == D(value)` when the new value is int/float or carries `.quantize`, else `old == value`, `None` handled symmetrically) and calls `touch(row)` only when at least one field genuinely moved, so `core.py`'s unconditional `touch()` is never reached by a no-op recompute. The rule is in fact broader than PRD stated — it also covers client-supplied replacement values (`PATCH /agents` with unchanged `skills`, or an empty body, is a 200 that does not bump `version`). The only unconditional touches are `cascade.py:348-353 move_shift_end` (only ever invoked with a genuinely different `end_at`, since OT/VTO `hours` >= 0.5) and `routes_partners.py:140`/`:296`, all covered by §2.9's pre-existing "except where this document explicitly states..." clause. No pass-1 edit needed qualifying.

Pass 2 also recorded, for pass 3: `cascade.py`'s `cycle_of_row` is dead code (the frozen gate is an explicit `require_not_frozen(cycle)` per route, so §2.8's enumeration is descriptive, not a dispatch table), and `recompute_interval_forecast`'s `excluded_event_ids` parameter is never passed by any caller, so no exclusion mechanism should be documented.

Deliberately declined as low-value by pass 2: intra-band ordering inside `create_planning_cycle`, marketing-event windows not being horizon-checked, `skills` array duplicate/length rules, the `_seq` third sort key in the reforecast replay (already covered by pass 1's §2.3 edit), and `check_weekly_hours` recomputing the projection instead of reading `scheduled_hours_committed` (arithmetically equivalent).

## Step 9 (pass 3 of 3): Complete PRD — routes_shifts.py / routes_bidding.py / routes_intraday.py / routes_partners.py — 2026-09-04T11:40:00.000Z

### Integrity check (final pass)
- `workspace/PRD_COMPLETED.md`: **458 lines / 127,712 chars before pass 3 -> 458 lines / 135,982 chars after.** Line count unchanged (all edits in-paragraph).
- Header count `27` — byte-identical to `PRD_FINALIZED.md`'s 27, so no section was added or lost.
- File still ends at the completed §5 error table, last row `| ERR_COMMITMENT_FLOOR_BREACH | 409 |` on line 458, not mid-sentence.
- Spot-read all edited bodies (§3.5 215–226, §3.6 231–242, §3.7 257–277, §3.8 279–299, §3.9 301–321): no garbled, truncated or duplicated fragment. Three cosmetic defects in pass 3's own new prose (a comma-splice at 221, an incomplete rationale at 225, an em-dash juncture at 231) were caught during the spot-read and repaired.
- Aligned line-by-line diff vs `PRD_FINALIZED.md` shows 53 revised paragraphs across all three passes, 26 of them pass 3's. Passes 1 and 2 untouched — nothing reverted or contradicted. Pass 3 built on pass 2's §3.5 template-code wording rather than restating it, added no competing universal to pass 2's §2.9 `set_fields` rule, and left the two licensed unconditional `touch(partner)` claims (§3.9 lines 309/315) alone after confirming them against `routes_partners.py:140` and `:296`.

### Tally
**40 discrete behavior statements** via ~32 `Edit` calls: **33 ambiguity-pins, 7 mismatch-revisions.** No new sections; one sentence appended inside §3.5's existing minting paragraph.

#### §3.5 — bid rounds and the award run (`routes_bidding.py`)
- insert — ambiguity — round `code` uniqueness is per-cycle, tested after `planning_cycle_id` resolves but before the frozen gate; `max_reopen_count` is an integer >= 0 defaulting to 2 — `routes_bidding.py:40,44-45`
- insert — ambiguity — the "no biddable template" and "no submitted bid" preconditions report generic `ERR_INVALID_STATE`, not `ERR_CYCLE_NOT_LOCKED` — `routes_bidding.py:96,98`
- insert — ambiguity — a bid member naming a template of another cycle is `ERR_VALIDATION`, but an unresolvable member reports `ERR_SHIFT_TEMPLATE_NOT_FOUND` first because resolution precedes the membership test — `routes_bidding.py:272`
- revise — **mismatch** — PRD called `created_at` "the only sanctioned tie-break"; the waterfall sorts on a third key, insertion order, so the text now names it and says no fourth is sanctioned — `routes_bidding.py:187`
- insert — ambiguity — a bidder whose agent `status` is not `ACTIVE` is skipped with their preference list never walked (ends `UNFILLED`), not refused — `routes_bidding.py:195`
- insert — ambiguity — `ERR_TEMPLATE_SLOTS_EXHAUSTED` also fires when no submitted bid belongs to an `ACTIVE` agent at all — `routes_bidding.py:195,212`
- insert — ambiguity — minting applies no labour ceiling and no skill re-test, so an award run may mint overlapping/over-long drafts that only fail at publication — `routes_bidding.py:241`, `cascade.py:480`

#### §3.6 — shift creation, publication, cancellation (`routes_shifts.py`)
- insert — ambiguity — direct creation checks existence + horizon only: template need not belong to the cycle, agent need not hold the skill nor be `ACTIVE` — `routes_shifts.py:38-45`
- insert — ambiguity — a minted shift's adherence fields (`out_of_adherence_seconds`/`excused_seconds` 0, `adherence_pct` 1.0000, `flagged_by_user_id` null) and `ot_hours`/`vto_hours` 0.00 — `cascade.py:480`
- insert — ambiguity — the rest rule's neighbour set is every non-`CANCELLED` shift of the agent, so a `DRAFT` neighbour constrains equally, bounded by neither cycle nor week — `cascade.py:388`, `routes_shifts.py:88`
- insert — ambiguity — "projected weekly hours" is the agent's entire `PUBLISHED` commitment plus the candidate, bounded by neither week nor cycle — `cascade.py:419`, `routes_shifts.py:90-93`
- insert — ambiguity — the consecutive-days run is over *distinct* `service_date` values and includes the still-`DRAFT` candidate — `cascade.py:437,455`
- revise — **mismatch** — PRD omitted `headcount_active` from the PUBLISHED->CANCELLED cascade; added — `routes_shifts.py:113`
- insert — ambiguity — DRAFT->CANCELLED cascades nothing, leaving `headcount_active` standing even if it removed the agent's last qualifying shift — `routes_shifts.py:116`

#### §3.7 — the three intraday levers (`routes_intraday.py`)
- insert — ambiguity — a field the chosen `kind` does not use is *forbidden* (non-null => `ERR_VALIDATION`, explicit `null` passes), and named ids are never cross-checked against each other or the cycle — `routes_intraday.py:72-90,92-96`
- insert — ambiguity — `expires_at` is required on a routing adjustment even though the lever never reads it — `routes_intraday.py:58`
- insert — ambiguity — a source group with no interval at that instant staffs zero (so every adjustment is refused, before any row is written); a missing *target* interval is harmless — `routes_intraday.py:104-112`
- insert — ambiguity — neither creation nor acceptance consults the shift's publication axis, so a `DRAFT` shift's `end_at` moves and only reaches the ledgers at publication — `routes_intraday.py:183`
- insert — ambiguity — revocation re-validates no labour rule, so it may leave an overlapping or over-long schedule — `routes_intraday.py:280`
- revise — **mismatch** — PRD listed `ACCEPTED` as terminal while also declaring `ACCEPTED -> REVOKED`; now "terminal in every direction but the revocation edge", with `ERR_ACTION_NOT_OFFERED` reserved for the three genuinely terminal states — `routes_intraday.py:256`

#### §3.8 — adherence, coaching, adjudication (`routes_shifts.py`)
- revise — **mismatch** — the universal "an observation or exception aimed at a shift that is not published is refused" was over-broad; narrowed to observation and *fresh filing*, plus a sentence that adjudication and resubmission never re-read the axis (an open case survives cancellation and can still reach `EXCUSED`) — `routes_shifts.py:139,178` vs `:213-286`
- insert — ambiguity — **`out_of_adherence_seconds` is bounded above by nothing, and specifically not by `scheduled_seconds`** — `routes_shifts.py:135`
- insert — ambiguity — a shift with zero `scheduled_seconds` scores 0.0000, the opposite convention to the agent rollup's empty-set 1.0000 — `calc.py:236-241`
- revise — **mismatch** — PRD implied OT/VTO re-derive the score; they recompute `scheduled_seconds`/`paid_hours`/`ot_hours`/`vto_hours` but leave `adherence_pct` (and the agent's pooled score) untouched until the next observation or approval — `cascade.py` `recompute_shift_hours`, `routes_intraday.py:219,239`
- insert — ambiguity — `flagged_by_user_id` is never cleared once stamped, so the flagging controller is barred from adjudicating for the shift's life — `routes_shifts.py:153,221`
- insert — ambiguity — no self-edge (a repeat same-verdict observation is `ERR_INVALID_STATE`) and `EXCUSED -> ON_TRACK` is undeclared, so an at-threshold observation on an `EXCUSED` shift is refused — `routes_shifts.py:122-128,144`
- revise — **mismatch** — "six observation-driven transitions" -> **five**, matching the declared edge set — `routes_shifts.py:122-128`
- insert — ambiguity — the pooled agent score is **not** clamped, so it can read below 0.0000 (reachable precisely because of the unbounded seconds above) — `cascade.py` `recompute_agent_adherence`
- revise — **mismatch** — PRD's "files against their own out-of-adherence shift" implied a status precondition; filing imposes none, any published shift with >= 1 out-of-adherence second qualifies, including one reading `ON_TRACK` — `routes_shifts.py:169,178,180`
- insert — ambiguity — the `duration_seconds` upper bound reads the shift row, so it runs after ownership, frozen and published gates yet still reports `ERR_VALIDATION` (422) — `routes_shifts.py:171-182`
- insert — ambiguity — `coach_note` is optional 1–500 chars, stored by all three branches only when present, never cleared to null — `routes_shifts.py:218,236,250,255`
- insert — ambiguity — on APPROVE the duration test runs *before* the `OUT_OF_ADHERENCE` state test, so a stale duration reports `ERR_VALIDATION` rather than `ERR_INVALID_STATE` — `routes_shifts.py:229-234`
- insert — ambiguity — REJECT also stores a supplied `coach_note` — `routes_shifts.py:249-251`
- insert — ambiguity — resubmission requires both `narrative` and `duration_seconds` and re-tests the duration against the shift's current value — `routes_shifts.py:265-266,277`
- insert — ambiguity — `info_requested_count` moves only on resubmission; the coach's `REQUEST_INFO` branch leaves it alone — `routes_shifts.py:254-257,284`

#### §3.9 — partners (`routes_partners.py`)
- insert — ambiguity — each `latest_sl_attainment_pcts` entry is an object with exactly two keys, `period_end_date` (10-char date) and `sl_attainment_pct` (4 dp) — `routes_partners.py:112-115`
- insert — ambiguity — remaining need ignores `PROPOSED` allocations, so a second waterfall run against an unchanged interval re-proposes the same volume — `routes_partners.py:212`
- insert — ambiguity — the waterfall's third sort key is insertion order behind rate and `created_at` — `routes_partners.py:218-219`
- insert — ambiguity — `delivered_volume` is >= 0 and *not* capped by `allocated_volume`, so over-delivery settles at full delivered quantity — `routes_partners.py:322`
- insert — ambiguity — the `DELIVERED_ONLY` payable is not floored at zero: it can go negative and drag `invoice_total_cents` down — `calc.py:208-212`

### Verdict on the `out_of_adherence_seconds` upper-bound lead
**Confirmed and pinned.** `routes_shifts.py:135` is `v_int(b, "out_of_adherence_seconds", minimum=0)` — no upper bound anywhere on that path, and `calc.adherence_score` clamps only the *per-shift* result (`calc.py:241`), never the pooled agent sum. §3.8's observation paragraph now states the field "is bounded above by nothing whatsoever, and in particular not by the shift's own `scheduled_seconds`," and §3.8's rollup paragraph cites exactly that as why pass 2's unclamped-pooled-score statement is reachable. The two statements interlock rather than one being an unexplained assertion.

No exclusion mechanism was documented for `recompute_interval_forecast`'s unused `excluded_event_ids`; no tests were run and no processes killed.

## Pipeline complete — orchestrator final verification — 2026-09-04T11:44:00.000Z

Step 9 totals across the three passes: **62 ambiguity-pins, 10 mismatch-revisions** (pass 1: 12/0, pass 2: 17/3, pass 3: 33/7).

Independent checks by the orchestrator:
- `PRD.md` 456 lines / 114,784 B; `PRD_FINALIZED.md` 458 / 116,780; `PRD_COMPLETED.md` 458 / 135,982.
- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the signature of a Step 9 scan that never ran) — `cmp` differs, and the aligned diff shows 53 revised paragraphs. `PRD_FINALIZED.md` likewise differs from `PRD.md`.
- 27 headers in `PRD_COMPLETED.md`, same as its source: no section added or dropped. Tail ends on the completed §5 error table.
- All 8 `workspace/implementation/results.$i.json` independently parsed: every round `passed 151 / total 151`.
- 151 tests on disk, 151 `Design:` tags, one per test, zero orphans; 89 of 90 non-stub design instances translated (the single skip is documented in the Step 5 entry).
