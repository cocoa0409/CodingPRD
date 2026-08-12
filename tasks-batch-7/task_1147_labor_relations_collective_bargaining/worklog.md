# Worklog — task_1147_labor_relations_collective_bargaining

## Step 1: Create task directory — 2026-08-11T02:37:00.000Z

Pre-assigned output folder `tasks/task_1147_labor_relations_collective_bargaining` and its `workspace/` subdirectory already exist. Step 1 auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T03:33:00.000Z

Clean lint on the final run. The scaffold package is complete. Summary of what was generated:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/`)

**`SCAFFOLD.yaml`** (§1.0–§1.7 only — no design keys)
- **Complexity profile**: multi-party negotiation × compliance/audit archetypes; flat topology; cyclic state machines; segregation-of-duties role model; layers = optimistic concurrency, cascading side effects, dual-variant calculation, ops-run checkpoint.
- **11 entities**: Union, CollectiveAgreement, Clause, BargainingSession, Proposal (self-referential counter chain), CostingScenario, RatificationVote, SideLetter, PastPractice, InformationRequest, ExpirationTask — every FK with canonical `FK -> X.id` prefix and a reverse-reachability GET.
- **11 state machines** with cycles (proposal counter rounds to a 12-round cap, costing rework loop, practice dispute/re-document loop, objection-withdrawn loop, EXPIRED⇄EXTENDED, side-letter legal-return loop) plus a depth-5 RATIFIED cascade (vote → successor ACTIVE → incumbent REPLACED → proposals IMPLEMENTED → side letters SUPERSEDED → clauses back to UNDER_REVIEW).
- **8 calculations** with pinned constants and rounding orders: dual-variant costing (PROVISIONAL vs FINAL), line-then-sum retro payout, dual-variant practice strength (LEGALISTIC vs OPERATIONAL), business/calendar deadline arithmetic, strict->-quorum / strict->-approval vote outcome, posture windows, task due-date propagation, envelope aggregation.
- **13 ordered validations, 52 endpoints, 30 errors, 6 roles** (UnionRepresentative is `entity_backed:Union`; two SoD pairs on user ids; two OCC rules on `CollectiveAgreement.version`); logical clock endpoint with pinned default `2026-05-01T00:00:00Z` and a 7-step epoch sweep.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 18 instances, exactly 2 per rule, all with structured `setup_api_calls`/`trigger` chains and literal asserts computed by executing the formulas (e.g., costing totals 256604833 vs 217008360; retro payout 32 vs the 33 a sum-then-round order would give; posture day-boundaries at 181/180/31/30 days).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 55 entries: 49 active instances across all nine guide sections (entities, state machines, calculations, validations ×2, endpoints, errors, rbac, cross-cutting layers, consistency) plus 6 `excluded_because` stubs that resolve to difficulty instances; every one of the 30 error codes has at least one triggering instance.

**Verification**: `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(52 endpoints, 11 entities, 18 §1.8 + 49 §1.9 active instances, 509 calls scanned.) Additional audits passed: no forbidden concurrency vocabulary, zero duplicate instance names across both design files, all enum values producible, all `excluded_because` stub targets resolve, all formula-derived asserts pre-computed as literals.

## Step 3: Copy shared files — 2026-08-11T03:34:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1147_labor_relations_collective_bargaining/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T03:40:00.000Z

All three hard contracts PASS. Final summary:

---

**PRD generated**: `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/PRD.md`

**Structure** (5 top-level sections, 12 §2 subsections, 12 §3 subsections):
- §1 Introduction (3 paragraphs — business context, scope, cross-cutting concerns)
- §2 Global Specifications: 2.1 RBAC with identity-prose per role, 2.2 verbatim response envelope (byte-identical to source), 2.3 Pagination, 2.4 Interval/scheduling discipline, 2.5 Union standing, 2.6 Posture & bargainable predicate, 2.7 OCC, 2.8 SoD, 2.9 Precision, 2.10 Common resource properties, 2.11 Reference resolution + validation priority ordering, 2.12 Logical clock & epoch sweep
- §3 Business Logic: 3.1 Union/agreement onboarding, 3.2 Clause interpretation workflow, 3.3 Sessions & proposal exchange, 3.4 Counter-proposals, 3.5 Costing scenarios (full formula translated to prose), 3.6 Ratification depth-5 cascade, 3.7 Retro payout, 3.8 Implementation voids, 3.9 Side letters, 3.10 Past practices (both strength variants), 3.11 Information requests, 3.12 Expiration planning & extend recompute
- §4 Endpoint table (4 columns: Method, Path, Description, Authorized Roles)
- §5 Error catalogue (2 columns: Error ID, HTTP Status Code) — 30 errors

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body-only fields (to_status, action, side_letter_id, past_practice_id, reason,
  new_expiration_date, expected_agreement_version, extra_business_days, to_iso8601): 9 required, 9 present, 0 missing
- endpoints[].query_params (limit, offset, plus shared FK/status filters): 6 unique, 6 present, 0 missing
Status: PASS (97/97 unique identifiers backticked in PRD)
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (§2.11 priority paragraph), 0 missing
- concurrency_rules[] OCC rejections: 2 checked (lock, extend), 2 expressed (expected_agreement_version + ERR_STALE_AGREEMENT_VERSION/412 named for both), 0 missing
- state_machines[].transitions: 50+ transitions across 10 entities, all from/to pairs named with actor and key side effects, 0 missing
- calculations[]: 7 checked (scenario_total_cost, ratification_retro_payout, past_practice_strength both variants, information_request_deadline, ratification_outcome, agreement_posture, expiration_task_due_date, envelope_commitment), all formulas translated to prose with constants embedded, 0 missing
- validations[] conditions: 13 priority levels checked, all matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all cascades (decertify, extend recompute, lock-supersede, ratify depth-5, abandon ripple, union decertified 2-link cascade) narrated, 0 missing
- entities[].fields[] structured content: defaults (deadline_mode=BUSINESS, is_economic=false, includes_benefits=false, one_time/recurring=0, round_number=1, posture=NEGOTIATING, envelope=0, extension_count=0, etc.) all stated
- sibling-branch symmetry: PROVISIONAL/FINAL, LEGALISTIC/OPERATIONAL, BUSINESS/CALENDAR, RATIFIED/REJECTED, ACTIVE→DECERTIFIED/TRUSTEED→DECERTIFIED all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 602
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verbatim block: PASS (byte-identical body against `section-2.2-response-structure.md`).

## Step 5: Generate unit tests — 2026-08-11T04:02:00.000Z

Generation complete. Summary:

## Files generated

**`test_helpers/`** (Stage 1):
- `types.py` — 10 entity TypedDicts (all with common fields per PRD §2.10), 15 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (34 endpoints total)
- `api_errors.py` — 31 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape checkers
- `factories.py` — payload factories for all 10 entities
- `constants.py` — PRD thresholds (HOURS_PER_YEAR, WAGE_DRIFT_CAP_PCT, TIER_*, CONTINGENCY_PCT, RETRO_PERIOD_DAYS, LEGALISTIC_DECAY, RESPONSE_BUSINESS_DAYS, SUNSET/CRITICAL_DAYS, MAX_ROUNDS, NEGOTIATOR_BUFFER_MINUTES)
- `test_users.py` — `TEST_USERS` shared headers + `make_union_representative_headers(union_id)` entity-backed builder (plus per-role makers)
- `fixtures.py` — Tier 1–5 composites: `create_union`, `create_draft_agreement`, `create_active_agreement`, `create_employer_proposal_on_table`, `create_union_proposal_on_table`, `create_computed_scenario`, `create_reviewed_scenario`, `create_locked_scenario`, `setup_accepted_economic_package`, `setup_open_vote`, `create_interpreted_clause`, `create_executed_side_letter`, `create_verified_practice`
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2): `conftest.py` + 13 test files with 79 tests total.

## Coverage audit
- Queue A (Difficulty): all 18 instances × ≥2 tests = 36 tests — each difficulty instance has exactly 2
- Queue B (Corner): all 33 non-stub instances × ≥1 test = 43 tests (some instances got 2 tests where the recipe naturally splits)
- The 6 `excluded_because` stubs (5 in corner index) were NOT translated; their assertions live in the cited difficulty instances
- Every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line verbatim from the source YAML
- Every test's docstring carries a verbatim PRD quote; a script verified a distinctive ≥8-word substring of each citation survives a literal `grep` of PRD.md — **all 79 pass**
- All files compile; `test_helpers` imports cleanly against a stub framework

## Key design decisions
- The `UnionRepresentative` role is entity-backed, so all ownership-gated calls (UNION proposal tender/accept/counter, tally, information-request create, clause DISPUTE) thread `make_union_representative_headers(union["id"])`, never the shared opaque constant.
- Setup chains from the design indices (e.g. `create_locked_scenario` for the recurring COMPUTED→REVIEWED→LOCKED chain) are fixture-level helpers reused by ~15 tests.
- Boundary tests pin PRD-exact values from the design YAML: PROVISIONAL total 256604833 / FINAL total 217008360, retro 32 (not 33), LEGALISTIC 0.83 vs OPERATIONAL 0.88, BUSINESS due 2026-05-15T17:00:00Z vs CALENDAR 2026-05-11T17:00:00Z, side-letter 2026-12-31 touching boundary = conflict.

## Step 6: Generate implementation — 2026-08-11T04:47:00.000Z

Implementation complete. All 10 smoke suites pass (264 checks) across repeated fresh boots.

## What was built

A complete Python + Flask implementation of the Labor Relations & Collective Bargaining API in `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/`:

- **`start.sh`** — executable launcher; guarded dependency install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py` in the foreground, binds `0.0.0.0:$PORT` (default 10000). Verified: three consecutive `bash start.sh` invocations boot cleanly in ~2s with an empty store each time.
- **`app.py`** — blueprint registration + error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`).
- **`db.py`** — in-memory store, empty at boot, no seeding; insertion counter for stable `created_at`-ordered pagination.
- **`clock.py`** — logical clock pinned at `2026-05-01T00:00:00Z` startup default; ISO-8601-with-millis serialization; lenient ISO parsing.
- **`calc.py`** — all calculations in `Decimal`: `scenario_total_cost` (PROVISIONAL amortized vs FINAL year-1 one-time, 0.15 drift cap before 1.32 benefits load, 0.80/0.50 coverage tiers, per-line ROUND_HALF_UP, reserve = 5% of subtotal after subtotal), `ratification_outcome` (ceil-half quorum, strict majority), `ratification_retro_payout` (monthly line rounded first, then × 30-day periods), `past_practice_strength` (LEGALISTIC 0.85^⌊years⌋ vs OPERATIONAL 5-year step, 4dp half-up), BUSINESS/CALENDAR deadline arithmetic (10 days, due 17:00:00Z, business days skip weekends starting the day after receipt), posture thresholds (180/30 calendar days).
- **`services.py`** — decertify cascade, incumbent supersession, clause supersede cascade, depth-5 RATIFIED cascade, REJECTED compensation revert, and the 7-step pinned epoch sweep.
- **`routes/`** — 12 modules covering all 43 endpoints.

## Key fidelity decisions

- Validation priority order follows PRD §2.11 (auth → role → ownership/side → shape → resolution → state → OCC → standing/SoD → scalar temporal → interval → caps → supporting gates → envelope); where the scaffold precondition lists disagreed (e.g., lock's SoD-vs-OCC order), the PRD ordering was used.
- Negotiator is employer-side but may not tender/accept — that yields `ERR_UNAUTHORIZED_ROLE`; opposite-side actions yield `ERR_WRONG_SIDE`.
- `union.open_information_request_count` is derived from the open-status set (so partial→fulfill never drives it negative); the union's version still bumps on every FULFILLED/PARTIALLY_FULFILLED transition per PRD §3.11.
- Mediator rule is half-open (adjacency allowed); negotiator 45-minute buffer uses expanded intervals with touching boundaries conflicting; side-letter overlap is closed-interval.
- OCC `expected_agreement_version` enforced on lock + extend only, returning 412 `ERR_STALE_AGREEMENT_VERSION`; envelope equality is permitted on accept.

Verified behaviors include the full compute math (cap, tiers at exactly 0.80/0.50, benefits ordering, amortization, reserve), SoD on review/lock/execute, lock-supersede, OCC staleness, ratification cascades both directions with retro payout, union standing chills, decertify cascade, extend→task-MISSED cascade, sweep boundary strictness (not expired/overdue at the exact instant), and the complete envelope shape including pagination meta fields.

Orchestrator note: route-pair verification after Step 6 confirmed the implementation registers exactly the 52 (method, path) pairs SCAFFOLD.yaml declares (0 missing, 0 extra).

## Step 7: Diagnostic sweep + fixes — 2026-08-11T04:40:00.000Z

8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 120s boot / 30s test timeout).

**Iteration 1**: 77/87 in every round; identical 10-test failure union across all 8 rounds (deterministic, not flaky).
- 9 failures were timestamp-format mismatches: implementation serialized every datetime as `.000Z`; tests assert whole-second form. PRD §2.9 ("Date and time arithmetic — `due_at`, `due_date`, `abandon_effective_date`, the ballot window — operates at whole-second precision in UTC"), §2.12 (clock "reads exactly 2026-05-01T00:00:00Z"), and §3.11 ("`due_at` is that date at 17:00:00Z") pin whole-second for business datetimes, while §2.10/§2.2 pin three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`. Tests faithful; implementation fixed.
- 1 failure (`test_lead_negotiator_buffer_conflict`): setup 409 on the exactly-45-minute-gap session. PRD §2.4 says "expand both candidate intervals by 45 minutes on each end, and if the two expanded intervals intersect ... rejected" — a 45-minute gap leaves expanded intervals overlapping by 45 minutes, so PRD-literal semantics reject it. The corner design's "gap of exactly 45 minutes is allowed" contradicts PRD (and the scaffold's own §validation text). STEP 1c split: kept the PRD-covered 30-minute-gap conflict assertion, removed the PRD-contradicting 45-minute-gap success assertion.

**Fixes applied**:
- `implementation/clock.py`: added `iso_seconds()` (whole-second `%Y-%m-%dT%H:%M:%SZ`); kept `iso()` (3 fractional digits) for created_at/updated_at/api_request_timestamp.
- `implementation/helpers.py`: `serialize()` split — business datetime fields via `iso_seconds`, `created_at`/`updated_at` via `iso`.
- `implementation/routes/clock_route.py`: `current_utc` now whole-second per PRD §2.12.
- `test_suite/test_12_validation_gates.py::test_lead_negotiator_buffer_conflict`: removed the exactly-45-minute-gap success assertion (PRD-contradicting); kept the 30-minute-gap ERR_NEGOTIATOR_BUFFER_CONFLICT assertion.

**Iteration 2**: all 8 rounds 87/87, 0 failed, 0 errors. Clean sweep — exit.

Subagent returned summary (verbatim):

Clean 8-round sweep achieved. Summary below.

## Summary

**Iterations run**: 2 (iteration 1: 10 deterministic failures in all 8 rounds; fixes applied; iteration 2: all 8 rounds 87/87, 0 failed, 0 errors).

**Tests deleted**: None. One test was partially split per STEP 1c (uncovered assertion removed, covered assertion kept):
- `test_lead_negotiator_buffer_conflict` (test_12_validation_gates.py) — unique-derivability collapse / PRD contradiction: the corner design (SCAFFOLD_CORNER_DESIGN.yaml `validations/lead_negotiator_buffer_conflict`) pinned "gap of exactly 45 minutes is allowed", but PRD §2.4 states verbatim "expand both candidate intervals by 45 minutes on each end, and if the two expanded intervals intersect … the create is rejected" — under that rule a 45-minute gap still leaves the expanded intervals overlapping by 45 minutes, so PRD-faithful implementations reject it. Removed the 45-minute-gap success assertion; kept the 30-minute-gap `ERR_NEGOTIATOR_BUFFER_CONFLICT` assertion (both readings agree → PRD-covered). Feedback for unit-test-generator: the scaffold corner design contradicted its own §validations text ("intervals expanded by 45 minutes on both ends intersect") — an arithmetic slip treating "45-minute buffer" as "gap < 45 conflicts" instead of "gap < 90 conflicts".

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `test_suite/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/test_suite/test_12_validation_gates.py` — `test_lead_negotiator_buffer_conflict`: removed the PRD-contradicting exactly-45-minute-gap success block (see above); docstring updated to match PRD §2.4 semantics.

**Fixes applied to `implementation/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/clock.py` — added `iso_seconds()` (whole-second `%Y-%m-%dT%H:%M:%SZ`); retained `iso()` (three fractional digits) for `created_at`/`updated_at`/`api_request_timestamp` per PRD §2.10/§2.2.
- `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/helpers.py` — `serialize()`: business datetime fields (`due_at`, `due_date`, `abandon_effective_date`, `start_at`/`end_at`, `effective_*`, `expiration_date`, `received_at`, observed dates, `ballot_close_at`) now serialize at whole-second precision per PRD §2.9 ("Date and time arithmetic … operates at whole-second precision in UTC"); only `created_at`/`updated_at` keep `.000Z`. This fixed 8 of the 9 format failures.
- `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/routes/clock_route.py` — `current_utc` in the clock-set response now whole-second per PRD §2.12 ("the clock reads exactly 2026-05-01T00:00:00Z"), fixing `test_clock_sweep_is_checkpoint_driven`.

**Flakiness findings**: none — the failure union was identical across all 8 rounds in iteration 1, and iteration 2 was uniformly clean. No timing-sensitive bugs surfaced.

## Step 8: Finalize PRD — 2026-08-11T04:45:00.000Z

PRD_FINALIZED.md is written. Summary below.

## Line counts
- `PRD.md`: 343 lines; `PRD_FINALIZED.md`: 343 lines (0.0% delta — three in-place sentence revisions/insertions, no new sections, no line-count change since each edit extended an existing paragraph line).

## Changes (one bullet per edit)

- **§2.4** — revise — pinned the lead-negotiator 45-minute buffer rule's boundary semantics: expanded intervals are treated as closed, so touching expanded boundaries count as a conflict (`ERR_NEGOTIATOR_BUFFER_CONFLICT`). This matches the implementation's `<=`/`<=` comparisons and the Step 7 test split, which kept the 30-minute-gap rejection and removed only the scaffold-pinned 45-minute-gap success assertion that contradicted the PRD — `implementation/routes/sessions.py:68-74`, `implementation/calc.py:43`.
- **§2.9** — revise — extended the existing whole-second-precision sentence to pin serialization: every resource-carried datetime field other than `created_at`/`updated_at` (the 13 business fields: `effective_date`, `expiration_date`, `start_at`, `end_at`, `ballot_close_at`, `effective_start`, `effective_end`, `first_observed_date`, `last_observed_date`, `abandon_effective_date`, `received_at`, `due_at`, `due_date`) renders at whole-second precision with no fractional digits; the three-fractional-digit form is reserved for `created_at`, `updated_at`, and meta `api_request_timestamp` — `implementation/helpers.py:249-268`, `implementation/clock.py:20-41`, `implementation/response.py:19`.
- **§2.12** — insert — pinned that the clock-advance response reports the new reading as `current_utc`, an ISO 8601 UTC timestamp at whole-second precision — `implementation/routes/clock_route.py:20-23`.

## Per-edit pre-edit search log

**Edit A (§2.4 buffer rule)**
- (a) Subject: boundary semantics of the lead-negotiator buffer-conflict check.
- (b) Paths enumerated: `implementation/routes/sessions.py:60-74` (the only conflict-check site; conflicts are checked only at session create — `transition_session` at lines 118-158 performs no interval checks); `implementation/calc.py:43` (`NEGOTIATOR_BUFFER = timedelta(minutes=45)`); the adjacent mediator rule at `sessions.py:64-67` (half-open, adjacency allowed — deliberately untouched); §3.3's cross-reference to "the lead-negotiator 45-minute buffer rule from §2.4" (consistent, no change); §2.11 validation ordering (mentions `ERR_NEGOTIATOR_BUFFER_CONFLICT`, unaffected).
- (c) Wording adjustment: mirrored §3.9's existing "touching boundaries counted as a conflict" phrasing, scoped strictly to the *expanded* intervals so the mediator half-open rule and its "adjacency is permitted" clause on the same line remain verbatim and un-contradicted.

**Edit B (§2.9 serialization precision)**
- (a) Subject: output representation precision of datetime fields in API responses.
- (b) Paths enumerated: `implementation/helpers.py:249-268` (`serialize()` — `_DT_SECOND_FIELDS` 13 fields via `iso_seconds()`, `_DT_MILLIS_FIELDS` `created_at`/`updated_at` via `iso()`); `implementation/clock.py:20-41` (both formatters); `implementation/response.py:19` (`api_request_timestamp` via `iso()` — three fractional digits, already pinned by §2.2); `implementation/routes/clock_route.py:21` (`current_utc` via `iso_seconds()`); `implementation/services.py:128-188` (sweep mutates datetimes but never formats them). Grepped all `strftime`/`isoformat`/`iso(` call sites — no other formatting path exists; no nested datetime fields in any payload (`transitioned` is integer counts, `year_breakdown_cents` is ints).
- (c) Wording adjustment: scoped the claim to "datetime-valued field carried on a resource" so it makes no claim about the non-resource `current_utc` readout (covered separately by Edit C) and explicitly reserved the millis form for `created_at`/`updated_at`/`api_request_timestamp`, keeping §2.2 and §2.10 verbatim-consistent.

**Edit C (§2.12 clock readout)**
- (a) Subject: the clock-set endpoint's response representation of the logical clock.
- (b) Paths enumerated: `implementation/routes/clock_route.py:13-23` (sole emitter of `current_utc`, via `iso_seconds()`); `implementation/clock.py:6` (startup default `2026-05-01T00:00:00Z` — matches §2.12's existing whole-second "the clock reads exactly…" sentence); all internal `clock.now()` consumers (posture, sweeps, `touch`, deadline arithmetic) never serialize the clock directly; `test_helpers/api_client.py:172` confirms the `to_iso8601` request shape already pinned by PRD.
- (c) Wording adjustment: phrased as "reports the clock's new reading as `current_utc`" rather than defining the full response body, so the implementation's additional `transitioned` field remains unpinned rather than excluded — avoiding a new mismatch by omission.

## Step 7 items requiring no PRD edit
- The `test_lead_negotiator_buffer_conflict` split itself required no direct PRD change beyond Edit A: under the PRD's expanded-interval rule the implementation already rejects the 45-minute gap; only the touching-boundary degree of freedom was genuinely undetermined, and Edit A pins it.
- No `test_helpers/` fixes were applied in Step 7, so none trace to edits.

## Step 9: Complete PRD — 2026-08-11T05:03:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Source vs output**: PRD_FINALIZED.md (343 lines / 56,083 chars) → PRD_COMPLETED.md (345 lines / 61,911 chars); delta +2 lines, +5,828 chars. 27 diff hunks, all inline in existing paragraphs; no new sections.

**Counts**: 23 ambiguity-pin insertions, 4 mismatch-revisions (2 edit sites were mixed, containing one of each).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl cite):

- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + 20 random uppercase alphanumerics — response.py:11-13
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock — response.py:19
- §2.2 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` (404) envelope — app.py:42-49
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_PAGINATION_INVALID` — helpers.py:174-181
- §2.3 — insert — ambiguity — `created_at` sort ties broken by insertion order — helpers.py:195-196, db.py:21
- §2.3 — insert — ambiguity — `has_more` defined as `offset + limit < total_count` — response.py:26
- §2.10 — insert — ambiguity — unknown `to_status` → `ERR_INVALID_REQUEST`; never-settable targets enumerated per resource → `ERR_INVALID_STATE` — sessions.py:124-132, proposals.py:173-176, scenarios.py:93-96, votes.py:89-92, letters.py:94-97, practices.py:105-108, requests.py:123-126, tasks.py:101-103
- §2.10 — insert — ambiguity — activate/archive/void-implementation accept an optional JSON-object body, ignored — helpers.py:59-71
- §2.11 — insert — ambiguity — path identifier resolved immediately after authentication, before body inspection — e.g. proposals.py:170-171
- §2.11 — revise — mismatch — rewrote the priority paragraph: path-resolution before shape; ownership/side/per-transition gates applied when their inputs become available (not strictly before shape/resolution); added `ERR_WRONG_SIDE` and 409 state-family ids to the chain; fixed typo `ERR_UNION_TRUSTED` → `ERR_UNION_TRUSTEED` — errors.py:25, votes.py:117-120, requests.py:48-56, proposals.py:88-100
- §2.12 — insert — ambiguity — clock accepts any well-formed `to_iso8601` (no forward-movement requirement) — clock_route.py:17-18
- §2.12 — insert — ambiguity — clock response also carries `transitioned` with the seven per-step mutation counts — clock_route.py:19-23, services.py:129-137
- §3.1 — insert — ambiguity — duplicate `union_code` → `ERR_INVALID_REQUEST` (400) — unions.py:26-28
- §3.1 — revise — mismatch — decertify cascade cancels every still-`SCHEDULED` session belonging to the union, not only those on just-archived agreements — services.py:21-26
- §3.1 — insert — ambiguity — agreement numeric integer fields carry no range constraint; invalid `deadline_mode` → `ERR_INVALID_REQUEST`; union standing not checked at creation — agreements.py:40-50
- §3.2 — insert — ambiguity — clause creation on `ARCHIVED`/`REPLACED` agreement → `ERR_INVALID_STATE` — clauses.py:46-47
- §3.3 — insert — ambiguity — cross-side drafting → `ERR_WRONG_SIDE`; drafting on `ARCHIVED`/`REPLACED` → `ERR_INVALID_STATE`; `clause_id` resolved for existence only — proposals.py:90-109
- §3.3 — insert — ambiguity — proposal born with `session_id`/`supersedes_proposal_id`/`estimated_year1_cost_cents`/`rejection_reason` null — proposals.py:123-129
- §3.3 — insert — ambiguity — accept/reject/withdraw performed by the side's designated role (UnionRep for EMPLOYER, ChiefNegotiator for UNION; withdraw mirror) — proposals.py:48-68
- §3.3 — insert — ambiguity — `envelope_committed_cents` defined as sum of `estimated_year1_cost_cents` over `ACCEPTED`/`IMPLEMENTED` proposals, null contributing 0 — calc.py:236-244, proposals.py:219
- §3.4 — insert — ambiguity — counter carries `proposal_type` over and records the countering operator as `submitted_by_user_id` — proposals.py:276, 285
- §3.5 — insert — ambiguity — scenario born with null user stamps and null cost aggregates; `proposal_ids` may be empty and are unresolved until compute; create gate on `ARCHIVED`/`REPLACED` — scenarios.py:35-56
- §3.5 — revise — mismatch — the `estimated_year1_cost_cents` overwrite at compute is silent: no `updated_at` refresh or version bump on the proposal (carve-out from §2.10's blanket rule) — scenarios.py:114-115
- §3.6 — insert — ambiguity — vote creation blocked on `ARCHIVED`/`REPLACED` (`ERR_INVALID_STATE`); `ballot_close_at` not clock-validated at creation — votes.py:37-41
- §3.6 — insert — ambiguity — ballot-window check runs before the locked-scenario and accepted-package gates — votes.py:94-106
- §3.6 — insert — ambiguity — negative `votes_for`/`votes_against` → `ERR_INVALID_REQUEST` — votes.py:124-125
- §3.9 — insert — ambiguity — letter's clause must belong to the named agreement (`ERR_INVALID_REQUEST`); creation blocked on `ARCHIVED`/`REPLACED` (`ERR_INVALID_STATE`) — letters.py:39-42
- §3.10 — insert — ambiguity — practice `clause_id` resolved for existence only — practices.py:44-45
- §3.10 — insert — ambiguity — abandonment ripple leaves the clause's `resolved_by_ref` intact — services.py:169-172
- §3.11 — insert — ambiguity — filing against an `ARCHIVED`/`REPLACED` agreement → `ERR_INVALID_STATE` — requests.py:57-58
- §3.11 — revise — mismatch — `open_information_request_count` maintained as the count of open-status requests (recomputed, not decremented): a `PARTIALLY_FULFILLED → FULFILLED` move leaves the count unchanged while still bumping the union's version — requests.py:177-179, helpers.py:235-240
- §3.11 — insert — ambiguity — extension: `extra_business_days` ≥ 1 else `ERR_INVALID_REQUEST`; not gated on request status; recomputes `is_overdue`; CALENDAR mode also holds 17:00:00Z — requests.py:190-201, calc.py:226-229
- §4 — insert — ambiguity — exact-match conjunctive query-parameter filter sets enumerated for all eleven list endpoints — routes/*.py list handlers

All other impl behavior walked (every endpoint, transition, formula in calc.py, sweep step, envelope shape, error catalog) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
