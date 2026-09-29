# Worklog — task_2441_school_attendance_boundary_redistricting

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2441_school_attendance_boundary_redistricting` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-02T18:10:00.000Z

All three scaffold artifacts for task 2441 are complete and the linter is clean.

Lint verdict (verbatim, run from the repo root as `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2441_school_attendance_boundary_redistricting`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2441_school_attendance_boundary_redistricting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2441_school_attendance_boundary_redistricting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2441_school_attendance_boundary_redistricting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  2043

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2441_school_attendance_boundary_redistricting/`):
- `SCAFFOLD.yaml` (187 KB) — §1.0–§1.7 only, no design keys. Domain `school-boundary-redistricting`, prefix `/redistricting`; 13 entities, 6 state machines + 3 §1.2.1 concurrency rules, 11 calculations, 60 validations, 53 endpoints, 60 errors, 5 roles + 2 segregation-of-duties rules. Profile: graph_constraint / quota_allocation, graph topology, cyclic state machine, immediate consistency, `expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (210 KB) — single key `scaffold_difficulty_design`; all 9 §0.5 rules, 20 instances (2–3 each).
- `SCAFFOLD_CORNER_DESIGN.yaml` (668 KB) — single key `scaffold_corner_design`; 9 sections, 93 instances (78 real recipes + 15 `excluded_because` stubs): entities 15, state_machines 17, calculations 13, validations 17, endpoints 6, errors 9, rbac 8, cross_cutting_complexity_layers 7, consistency_model 1.

Verified beyond the lint: all 93 corner names plus the 20 difficulty names are globally unique; every stub's `difficulty_instance` resolves to a §1.8 name (normalized to `rule_id / instance` form) and carries no `test_recipe`; all 60 error ids in the catalog are referenced by at least one design instance; every claim-type row of the extraction guide that applies to this domain is represented.

One SCAFFOLD.yaml fix was needed to reach a clean lint: `POST /redistricting/adoptions` listed `regime_years`, `transfer_cap_pct`, `variance_tolerance_pct` and `votes_abstain` as required inputs even though `AdoptionRecord` declares defaults for them (3, 95.0, 3.0, 0), which contradicted the defaults corner instance. They are now `"regime_years?"`, `"transfer_cap_pct?"`, `"variance_tolerance_pct?"`, `"votes_abstain?"` (quoted so PyYAML keeps them as flow scalars).

The hard constraint was honored throughout: no sibling `task_*/` directory was listed, read, or grepped — only the scenario text, the scaffold-generator skill, its claim-extraction reference, and this task's own files.

## Step 3: Copy shared files — 2026-09-02T18:10:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T18:27:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — 398 lines, ~12,900 words.

**Sections written**
- §1 Introduction (3 paragraphs: pain point, scope under `/redistricting`, three commitments — derived facts computed, ordering pinned, time explicit)
- §2 Global Specifications — 2.1 Identity/Roles/SoD, 2.2 API Response Structure (pasted byte-identical from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Record Properties & Version Semantics, 2.5 The Logical Clock, 2.6 Precision/Rounding/Boundary Inclusivity, 2.7 Optimistic Concurrency (all 3 rules), 2.8 Path Resolution & Single-Study Referential Integrity, 2.9 Cascade Determinism & Processing Order, 2.10 Validation Precedence (22-tier ladder mapping all 60 error IDs; ladder order verified to match the scaffold's `priority` values exactly)
- §3 Business Logic & Workflows — 9 subsections: 3.1 study setup + seed inventory + adjacency graph, 3.2 housing pipeline + rolling absorption cap + 4-link entitlement cascade, 3.3 projection runs (both variants), 3.4 assignments + program placement, 3.5 the four scoring calculations + three structural gates, 3.6 engagement/triage/revision cycles, 3.7 board vote arithmetic + regime windows + 3-link adoption cascade + phase-in rules, 3.8 activation 4-link cascade + transfer eligibility waterfall + seat pool + decide + window close + rescind compensation, 3.9 variance monitoring + closure
- §4 Endpoint Definitions — intro paragraph + 4-column table, **53/53 endpoints**
- §5 Error Code Catalogue — 2-column table, **60/60 errors**. File ends here with no audit footer.

**Hard Contract reports**
1. **Field-Name Coverage — PASS.** Programmatic diff (run twice; first run was a false negative caused by the fenced JSON block breaking backtick pairing, fixed by stripping fences): 121 required tokens from all 13 entities' `fields[].name` plus every endpoint `input` identifier — 0 missing. A second sweep of nested/sub-object keys (`walk_distance_miles`, `bus_minutes`, `has_safe_route`, `program_type`, `seats`, `base_students`, `development_students`, `critical_school_ids`, `per_school`, `previous_utc`, etc.) — 0 missing. All 36 calculation constants verified present by value.
2. **Rule Coverage — PASS.** All 11 calculations have prose formulas with pinned rounding order; all 6 state machines' transitions covered (every `from → to` pair either in arrow notation or explicit prose — arrow notation added for the adoption, transfer-request, comment-dismiss and scenario-rejection edges); all 3 OCC rules with write endpoint, `expected_*_version` field, error ID and HTTP 412; all 60 validations placed in the precedence ladder and contextually restated at their point of use with `applies_to` scopes; field-level defaults/types in §2.4 and §3.
3. **§3 Path Purity — PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; zero raw `/redistricting…` mentions in §3. One `==` pseudocode leak found in the §4 table description and rewritten. No fuzzy hedging words.

**Judgement calls on scaffold contradictions** (each resolved to one unambiguous reading, none left ambiguous in the prose):
- Identity headers rendered as `X-User-ID` / `X-User-Role` per SKILL.md, not the scaffold's `X-Role`.
- Pagination: max effective `limit` 100 (higher served as 100); `limit` outside 1–200 or negative `offset` → `ERR_INVALID_REQUEST`.
- `revision_round` increments on *entering* `REVISION`, unchanged on return to `UNDER_REVIEW` (endpoint spec preferred over the state-machine side-effect note).
- `close-monitoring` blocking test: resolved as **latest-observation-per-school by creation order**, the only reading under which both the validation and the endpoint promise are simultaneously satisfiable and the documented recovery path is reachable.

Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator truncation check:** `tail` of PRD.md ends inside the complete §5 Error Code Catalogue table at `ERR_NO_ELIGIBILITY_BASIS | 409` — a real section boundary, not mid-sentence. Section headings §1–§5 all present. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:20:00.000Z

Test infrastructure and test suite are complete and audited.

## Files written

**`test_helpers/` (9 files)** — `constants.py` (domain thresholds), `types.py` (5 roles, 20 enums, 13 entity TypedDicts with correct `common_fields` branching), `api_errors.py` (all 60 error ids + HTTP status map registered at import), `api_client.py` (53 endpoint methods, verified 1:1 against the PRD endpoint table, plus the clock endpoint), `test_users.py` (8 callers across the 5 roles), `factories.py` (payload builders), `assertions.py` (per-entity shape assertions + domain invariants), `fixtures.py` (primitives plus an 8-rung shared Riverbend ladder: `riverbend_locked` → `riverbend_adopted`), `__init__.py` (barrel export).

**`test_suite/` (10 files)** — `conftest.py` plus 9 numbered test files.

## Test counts

**116 tests, all tagged, 0 audit problems.**

- Queue A (difficulty): 38 tests across `test_01`–`test_03`, covering **19 of 20** instances at ≥2 tests each.
- Queue B (corner): 78 tests across `test_10`–`test_15`, covering **78 of 78** non-stub instances at ≥1 test each.
- The 15 `excluded_because` stubs emitted nothing; I verified all 15 cross-references resolve to real difficulty instances and that no test carries a stub tag.
- Every quoted PRD citation verified to appear verbatim in `PRD.md`; no file mentions "scaffold"; suite compiles and pytest collects all 116.

## Instances skipped (1)

`Difficulty/priority_pair_validation_conflict/assignment_level_mismatch_prefers_referential_over_safety` — **unreachable, gap left as a gap.** The recipe needs an ELEMENTARY area registered with a travel option naming a MIDDLE school, but `PRD.md:165` requires that every referenced school's `level` "must equal the area's `grade_band`", so that planning-area registration is itself rejected. Even granting the setup, tier 16 (`PRD.md:143`) orders `ERR_TRAVEL_OPTION_MISSING` ahead of `ERR_SCHOOL_LEVEL_MISMATCH`, and `level` is not PATCHable — so `ERR_SCHOOL_LEVEL_MISMATCH` can never surface on an assignment call. Not weakened, not marked skip/xfail.

Worth flagging: as a consequence, **`ERR_SCHOOL_LEVEL_MISMATCH` is asserted by no test in the suite.** It *is* reachable at planning-area registration, but no design instance targets it there, and the design-index-only contract forbids inventing one. A future design-index revision should add that instance.

## Recovery worth noting

`Corner/state_machines/revision_loop_beyond_the_third_round_rejected` was initially skipped, and I recovered it. The instance's literal recipe is unreachable (`PRD.md:235`'s "the same limit blocks a further resubmission" means a scenario can never sit in `UNDER_REVIEW` at `revision_round == 3`, so its asserted 4th push-back never happens), but the same sentence uniquely derives a reachable refusal: drive the loop to round 3, then the third *resubmission* is refused with 409 `ERR_REVISION_LIMIT_EXCEEDED`. That preserves the instance's off-by-one discrimination, so it is a faithful translation rather than a weakening. Corner coverage went 77/78 → 78/78.

## Corrections surfaced during translation

Two `test_helpers/fixtures.py` fixes: `activate_adoption` defaulted to a planner caller although the PRD reserves activation to `TransferOfficer`; and the Riverbend area builders were private, forcing duplication, so `riverbend_area_builders()` is now exported.

Design-index-vs-PRD discrepancies the PRD-first filter caught, each resolved in the PRD's favour: an undeclared `activated_at` field; undeclared `per_school` entry field names; `max_utilization_pct` corrected to 94.81 for the impact-analysis instance (the slice omitted program-placement seats from a school's load); absolute `version == 1/2` literals replaced where PRD roll-up recomputation provably pushes versions higher; the decide-time window guard corrected to `ERR_ADOPTION_STATE_INVALID`; header `X-Role` corrected to `X-User-Role`; non-existent enum members and error ids replaced (`WALKABILITY` theme, `HARDSHIP_REVIEW` rule type, `ERR_SEED_DATA_LOCKED`); and adjacency-listing `total_count` expectations corrected because the PRD mints symmetric mirror rows.

(Sub-agent addendum, verbatim — a queue-B helper agent that recovered the skipped state-machine instance:)

Re-opened the skipped instance and added the test. On my own re-reading of the PRD I agree the refusal is uniquely derived — but only in the reachable rendering, not the instance's literal recipe.

**File:** `test_suite/test_11_corner_state_machines.py` — now **13 tests** (`python3 -m py_compile` OK; the module also imports cleanly, so every symbol resolves).

**New test:** `test_revision_loop_beyond_the_third_round_rejected`, tagged `Design: Corner/state_machines/revision_loop_beyond_the_third_round_rejected`.

Precedence, re-verified against the PRD rather than taken on trust — at the refused third resubmission: study is `ENGAGEMENT` (admitted by PRD.md:209); scenario is in `REVISION`, so the tier-10 `ERR_SCENARIO_NOT_EDITABLE` gate passes; the test creates no housing development and no second run, so `projection_stale` stays false and tier 13 passes; the tier-19 structural gates pass (three areas assigned exactly once, Cedar's A-01/A-02 adjacent, Birch's lone A-03 vacuously contiguous, `DUAL_LANGUAGE` placed once at a school that has assignments); tier 21 capacity passes at 89.26. That leaves `ERR_REVISION_LIMIT_EXCEEDED` (tier 20, PRD.md:147) as the only reachable outcome, and PRD.md:235 names that id explicitly for "a further resubmission of such a scenario" — so the id comes from the rule sentence, not from the tier list.

Test shape: three guardians file comments on A-02, each triaged `TRANSPORTATION`/`MEDIUM` while the scenario is `UNDER_REVIEW` (one per round, since each push-back consumes its cited comments). The coordinator — never the author — pushes back three times, asserting `REVISION` + `revision_round` 1/2/3 + `revision_reason` `COMMENT_CYCLE` after each, so the off-by-one discrimination is exercised at every rung rather than only at the end. The two intervening planner resubmissions assert `UNDER_REVIEW` with `revision_round` unchanged and `revision_reason` cleared to null (PRD.md:209). The third resubmission is the refused call; per PRD.md:211 the post-refusal re-read checks status still `REVISION`, `revision_round` still 3, `version` unmoved, `revision_reason` still `COMMENT_CYCLE`, and all nine stored score fields byte-identical — compared against a pre-call snapshot rather than hardcoded literals. The instance's unreachable "fourth push-back from `UNDER_REVIEW` at round 3" recipe is not tested.

The only other change to the file was adding `request_revision` to the existing `test_helpers` import. No other file touched, no other task directory read, no skip/xfail markers.

**Status of the earlier report:** the "1 instance skipped" line is superseded for corner queue — all 13 non-stub state-machine instances are now covered. The three previously reported assertion-level deviations still stand (dropped `study.version == 2` as PRD-underivable at 2; `data_locked_at` compared as an instant prefix because the PRD mandates three fractional digits; the A-03 adjacency assertion restated as "exactly one returned row has `area_id` == A-03 and is `is_reciprocal` true", since the PRD's listing returns both endpoints' rows).

## Step 6: Generate implementation — 2026-09-02T19:20:30.000Z

Implementation complete and verified end to end.

## Files written (all under `workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` (exec) | `cd` to own dir, guarded `pip install` (skipped when Flask imports), `exec python3 app.py` |
| `app.py` | `create_app()`, 4 blueprints (3 under `/redistricting`, clock un-prefixed), `ApiError`/`HTTPException` handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `core.py` (27 KB) | Envelope/meta builders, `req_`+20-char ids, 5-role auth (`X-User-Role` with `X-Role` fallback), the full 60-entry error catalog, in-memory `Store` (13 dicts + logical clock at `2026-08-01T00:00:00Z`), body/query validators, pagination, `Decimal`/`ROUND_HALF_UP` helpers, per-type 404 lookups, derived-field recomputation |
| `calc.py` (12 KB) | 11 calculations + all domain constants (cohort survival 0.98, unit yields, entitlement weights, bus 71/95.00/1.85/15-min/180-day, walk & ride limits, 110.00 ceiling, 15.00 supermajority trigger, 2-year regime gap) |
| `services.py` (11 KB) | Adjacency map, projection execution (keeps internal per-development rounded contributions so `PROJECTED_BASED` inherits them verbatim), scenario scoring, seat-pool, eligibility waterfall |
| `routes/{setup,planning,implementation,clock}.py` | 53 route handlers |
| `requirements.txt` | `flask` |

**53 routes registered** = 52 PRD §4 endpoints under `/redistricting` + `POST /_clock/set_current_utc`. Storage is in-memory only (verified: no `open(`/`sqlite`/`json.dump`/`pickle` anywhere; all 13 tables empty at import).

## Verification performed
- **Booted from a real fresh process** (`PORT=10731 bash start.sh`): listening in <3 s, correct envelopes over HTTP for a 404, a create, a list (with pagination meta) and the clock endpoint; `exec` means the runner's port-kill hits the actual server PID.
- **Three scripted end-to-end suites, all 0 failures** (run against the WSGI app, then deleted): full happy path study→closure; a gate/precedence suite; an edge suite. Between them they exercise every state machine, all 5 cascades, both projection variants, both impact variants, seat-pool ordering, and ~45 distinct error ids.
- Hand-checked numbers matched exactly: projections (`147/39/29`, dev-weighted `90+10.5→101`, entitled `25.2`), `max_utilization_pct 104.67`, `transport_cost_annual_usd 113022.00`, `walk_eligible_pct 18.14`, `students_reassigned_pct 31.63`, `frl_dissimilarity_index 0.3934`, variance `6.67 WATCH` / `14.29 CORRECTIVE` / `-2.86 WITHIN_TOLERANCE`, quorum/supermajority whole-number arithmetic, regime gaps (overlap/abut/1-year rejected, 2-year accepted, rescinded interval reusable), waitlist auto-promotion order-sensitivity (earlier candidate takes the last seat), and rescission restoring the exact pre-activation head counts.
- Programmatic diff of the error catalog against PRD §5: **60/60 ids present, zero extras, zero HTTP-status mismatches**.

## Notable interpretation decisions (worth flagging)
1. **PRD §2.10's 22-step ladder is authoritative over §3 prose.** So `ERR_TRAVEL_OPTION_MISSING` → `ERR_SCHOOL_LEVEL_MISMATCH` → `ERR_CROSS_STUDY_REFERENCE` (group 16): assigning a foreign-study school reports the travel-option error, and a travel option naming a wrong-level foreign school reports level mismatch. Likewise `ERR_REVISION_LIMIT_EXCEEDED` (group 20) sits after the structural gates and before `ERR_SCHOOL_CAPACITY_CRITICAL` (group 21), and `decide` checks the adoption window before decidability (group 12 order).
2. Planning-area `travel_options` enforce `school.level == area.grade_band` at creation; the seed lock only requires *at least* one entry per ACTIVE same-level school being exactly one — leftover entries for mothballed schools do not block locking (verified reachable).
3. `comment_intake_open` and `scenario.projection_stale` are computed (`status == ENGAGEMENT`, `run.status == STALE`); `submit-for-review` gates on `run.status != COMPLETE` so SUPERSEDED also blocks.
4. Existence (404) resolves before schema (422) via a `pre_resolve` helper that only resolves well-formed ids; SoD (403) resolves its target internally and defers to the 404 when unresolvable.
5. Ordering uses `(created_at, _seq)` everywhere because the logical clock does not advance on its own — every record carries a monotonic private `_seq`, and all `_`-prefixed keys are stripped from responses.
6. Version bumps happen at most once per record per request and only when a stored value actually changed, except the six endpoints the PRD explicitly says increment the study version.

## Step 7: Run tests and iterate — 2026-09-02T19:45:00.000Z

All green. Final state verified.

## Summary

**Iterations run: 3** (each a full 8-round parallel sweep under `setsid nohup`). Final sweep: **8/8 rounds at 116/116 passed**, 0 failed / 0 errors / 0 skipped. The 8 `results.*.json` files are left in `workspace/implementation/` as evidence.

### Tests deleted
None. One *assertion* was removed via STEP 1c partial-coverage split (below); no whole test was deleted.

### Fixes applied to `test_suite/`

- **`test_suite/test_14_corner_endpoints_consistency_layers.py`** — `test_impact_analysis_is_a_pure_computed_read`: expected `max_utilization_pct` corrected `94.81` → `89.26`. **Test bug (STEP 2, assertion mis-transcription).** The assertion's own failure message already stated the correct inputs ("Cedar carries 452 assigned students plus 30 program seats against 540 seats"), and PRD.md:215 uniquely determines the result — `100 * 482 / 540 = 89.26`. `94.81` is `512/540`, i.e. the author double-counted the 30 program seats. Corroborated empirically: the identical `riverbend_under_review()` ladder asserts 89.26 in eight other passing tests (test_01:531, test_02:114/600, test_03:857/1216, test_12:88/95, test_13:839/977, test_15:677), and the fixture has exactly one 30-seat placement at Cedar. The fix makes the test *more* faithful to PRD, not less.

- **`test_suite/test_15_corner_errors_and_rbac.py`** — `test_pagination_and_enum_query_inputs_out_of_range_are_rejected`: removed only the `grade_band="K8"` **query-filter** rejection assertion; kept the `limit=0`, `offset=-1` and well-formed-page assertions. **STEP 1b collapse — ENUM-MEMBERSHIP-ONLY.** PRD says only that planning-area listings are "filterable by `study_id`, `current_school_id`, `previous_school_id` and `grade_band`" (PRD.md:169) and never states that an out-of-member *filter value* is rejected. The two admissible readings: (A) §2.10 tier 5's "an enum value outside its declared member list" reaches query params → 422; (B) that clause continues the body-field enumeration it opens with ("a required input field absent or null"), and a filter is a pure predicate matching zero rows → empty 200. Reading (B) is supported by the fact that `limit`/`offset` got their *own* dedicated validation sentence in §2.3 precisely because query params are not otherwise validated, and that unknown `study_id`/`current_school_id` filter values likewise return empty rather than 404. Body-level enum rejection remains covered by `test_10_corner_entities.py:585`, which passes.

### Fixes applied to `test_helpers/`
None required.

### Fixes applied to `implementation/`

- **`workspace/implementation/app.py`**, `__main__` block: `app.run(..., threaded=False)` → `threaded=True`. Fixed a real transport defect surfaced only by the parallel sweep: round 2 of iteration 2 failed `test_entitlement_advance_skipping_or_reversing_a_stage_rejected` with `ChunkedEncodingError: IncompleteRead(0 bytes read, 527 more expected)` while the other 7 rounds were clean. With `threaded=False` Werkzeug serves one connection at a time, so a stale keep-alive socket left in the client pool from the previous `per-test-server` reboot (same port each round) blocks or truncates the next connection's response. This changes no PRD-visible behavior — no endpoint, field, side effect, header or capability was added. Independent confirmation: per-round wall time dropped from **351s to 223s**, showing the runner had been stalling on blocked sockets rather than the failure being mere CPU contention.

### Notes
- No `pytest.mark.skip` / `xfail` anywhere in the suite (verified); no `error_id` assertion was downgraded to an HTTP-status assertion; no PRD-required implementation check was weakened.
- Storage remains in-memory only; no seeding or on-disk persistence was introduced.
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read.

**Orchestrator independent verification of the sweep artifacts:** all 8 `workspace/implementation/results.{1..8}.json` exist (~35.8 KB each, written 19:39) and each parses to `passed 116 / total 116 / failed 0 / errors 0 / skipped 0`. Claim confirmed, not taken on trust.

## Step 8: Finalize PRD — 2026-09-02T19:50:00.000Z

## Result

`workspace/PRD_FINALIZED.md` written. **398 → 400 lines (+2, +0.50%)** — one inserted paragraph (plus its blank separator line); everything else byte-identical to `PRD.md`.

### Changes

- **§2.3 Pagination** — *insert* — after the ordering/`meta` paragraph, pins that list **filter** query parameters are plain equality predicates and are **not** subject to §2.10 tier-5 enum-membership validation: an out-of-member filter value yields HTTP 200 with an empty page rather than `ERR_INVALID_REQUEST`; an omitted or empty filter narrows nothing. — `implementation/routes/setup.py:353-357`, `implementation/core.py:407-410` (`as_enum` reached from body only)

### Step_7_diff items that needed no PRD edit

- **`test_14` `max_utilization_pct` 94.81 → 89.26** — pure test-fixture arithmetic bug. `PRD.md:215` already uniquely determines the load as assignment `projected_students` **plus** program `seats`, counted once; `implementation/services.py:107-110` does exactly that (`load = Σ projected_students`, then `load += Σ seats`), giving `100*482/540 = 89.26`. PRD prose kept verbatim.
- **`app.py` `threaded=False → True`** — transport/process-hosting detail with no PRD-visible surface (no endpoint, field, header, side effect or capability). No edit; the PRD says nothing about the WSGI server and should not start.

### Per-edit pre-edit search log

**Edit 1 — §2.3 filter-value semantics**

(a) **Subject identified:** how a list endpoint interprets a query-parameter *filter value* — validation vs. predicate — plus what `limit`/`offset` validation remains, and what an empty filter means.

(b) **Impl paths enumerated (read or grepped):** every `request.args`/filter site in the service, via `grep -n "request.args\|bool_filter\|paginate(" routes/*.py`, then read each block:
- `routes/setup.py:226-232` schools list (`level`, `status`); `:353-357` planning-areas (`study_id`, `current_school_id`, `previous_school_id`, `grade_band`); `:419-422` adjacencies (`is_reciprocal`, via `bool_filter`); `:487-491` housing developments (`unit_type`, `entitlement_status`)
- `routes/planning.py:133-139` projection runs (`variant`, `status`); `:217-221` scenarios (`study_id`, `projection_run_id`, `status`, `impact_variant`); `:497-504` assignments (`scenario_id`, `area_id`, `assigned_school_id` + `is_superseded` via `bool_filter`); `:552-556` comments (`scenario_id`, `area_id`, `status`, `theme`, `priority`)
- `routes/implementation.py:185-189` adoptions (`study_id`, `scenario_id`); `:241-244` phase-in rules (`rule_type`); `:466-475` transfer requests (7 keys incl. `status`, `resolved_reason`); `:571-575` variance observations (`adoption_id`, `school_id`, `flag`)
- `core.py:437-456` `pagination()` (only `limit`/`offset` are range-checked, `limit>200`/`<1`/negative `offset` → 422, effective limit `min(limit,100)`); `core.py:459-468` `bool_filter()` (**does** reject a non-boolean token with `ERR_INVALID_REQUEST`); `core.py:407-410` `as_enum` and all 20 of its callsites — **every one is a request-body field**, none a query parameter.

Uniform result: all 30-odd non-boolean filters are `if value: rows = [r for r in rows if r[key] == value]` — no membership check, empty string treated as absent.

(c) **Wording adjustment made:** two, both to avoid a false universal.
1. `bool_filter` *does* 422 on a malformed value, so an unqualified "filter values are never rejected" would have been a new mismatch against `is_reciprocal` / `is_superseded`. Scoped the non-rejection claim to "outside the filtered field's declared **enum** member list" and to "the **enum-membership** check of §2.10" — boolean filters have no declared enum member list, so the sentence makes no claim about them and leaves their 422 intact.
2. Added "omitted or supplied empty is no filter at all": a bare "equality predicate" reading would make `?previous_school_id=` match nothing, whereas impl's `if value:` treats it as unfiltered — a real divergence on the nullable-FK filters. Also opened with "Beyond `limit` and `offset`" so the paragraph cannot be read as loosening the pagination range checks that §2.3 sentence 1 and `core.py:437-456` still enforce.

## Step 9: Complete PRD — 2026-09-02T20:02:00.000Z

Done. `PRD_COMPLETED.md` written.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` 400 lines / 95,538 chars → `workspace/PRD_COMPLETED.md` 400 lines / 100,732 chars (**+5,194 chars**, 0 net lines — every change is an in-place revision of an existing line; no new sections or paragraphs).

**Counts:** 26 lines touched carrying 33 discrete changes — **23 ambiguity-pins**, **10 mismatch-revisions**.

### Changes

- §2.1 — revise — mismatch — an absent/empty `X-User-Role` falls back to an `X-Role` alias; header values are trimmed (whitespace-only = empty); an unrecognised role name yields `ERR_UNAUTHORIZED` — core.py:321-333
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from wall-clock time, not the logical clock — core.py:288-292
- §2.3 — insert — ambiguity — `meta.limit` echoes the capped effective value; non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty = omitted — core.py:437-456
- §2.3 — insert — ambiguity — `is_reciprocal`/`is_superseded` accept only `true|false|1|0`, else `ERR_INVALID_REQUEST` (not the tolerant filter rule) — core.py:459-468
- §2.4 — insert — ambiguity — a recomputation landing on the stored value moves neither `updated_at` nor `version` — core.py:670-712
- §2.4 — insert — ambiguity — `planner_notes`/`revision_notes`/`agenda_notes`/`dismissal_notes`/`closure_notes`/`rescind_reason` are validated but never persisted; only `decision_notes` is stored — planning.py:290, implementation.py:308
- §2.8 — insert — ambiguity — planning-area body reference order: `study_id` → `current_school_id` → each travel option's `school_id` — setup.py:291-302
- §2.9 — insert — ambiguity — records sharing `created_at` are ordered by server insertion sequence — core.py:268-271
- §2.9 — revise — mismatch — a cascade link bumps `version` only where it actually changes the record — core.py:670-679
- §2.10 #5 — insert — ambiguity — empty required strings and non-numeric/non-integer values are schema failures — core.py:359-398
- §2.10 #5 — revise — mismatch — the empty-array rule applies to the `program_placements` **replacement** only; the initial array may be empty — planning.py:59-74, 163
- §3.1 — insert — ambiguity — school adjustment is ungated on study phase (works even under `CLOSED`), and a no-field PATCH still bumps `version` — setup.py:241-259
- §3.1 — revise — mismatch — registration itself accepts `status: MOTHBALLED`; adjustment is not the only route — setup.py:195-197
- §3.1 — insert — ambiguity — travel-option level mismatch → `ERR_SCHOOL_LEVEL_MISMATCH`, checked before `ERR_CROSS_STUDY_REFERENCE`; `current_school_id` is never level-checked — setup.py:315-323
- §3.2 — insert — ambiguity — developments may be added in any study phase except `CLOSED`; the seed lock does not freeze the pipeline — setup.py:444-446
- §3.2 — insert — ambiguity — entitlement advance is ungated on study phase — setup.py:500-513
- §3.2 — revise — mismatch — link two recomputes `projection_stale` as "any run is `STALE`", so an advance with no `COMPLETE` run leaves flag and study `version` untouched — setup.py:522-529, core.py:696-699
- §3.2 — insert — ambiguity — the cascade ignores the revision limit and can carry `revision_round` past 3 — setup.py:539-543
- §3.4 — revise — mismatch — initial `program_placements` is optional, defaults to empty and may be supplied empty — planning.py:163-164
- §3.4 — insert — ambiguity — the initial array gets the same ACTIVE / cross-study / host-capable checks as a replacement — planning.py:171-181
- §3.4 — insert — ambiguity — assignment creation and placement replacement are gated on scenario state only, never on study phase — planning.py:265, 445
- §3.5 — revise — mismatch — the submission freshness gate reads the cited run's live `status` (must be `COMPLETE`), not the stored flag; a merely `SUPERSEDED` run blocks submission while leaving `projection_stale` false — planning.py:298-300
- §3.5 — revise — ambiguity — `per_school` entries carry `school_id`, `utilization_pct`, `band`, in school creation order — services.py:114-118
- §3.6 — revise — mismatch — either authorized role may push back from either source state; role is never matched to source state, and the `BOARD_READY` path has no study-phase gate — planning.py:337, 354-357
- §3.6 — insert — ambiguity — certification reads the stored `projection_stale` flag, not the run's status — planning.py:416
- §3.7 — revise — ambiguity — adoption link three walks comments in creation order *within* each rejected scenario, scenarios in creation order — implementation.py:168-173
- §3.8 — insert — ambiguity — a non-`ADOPTED` scenario at activation → `ERR_ADOPTION_STATE_INVALID` — implementation.py:259-260
- §3.8 — insert — ambiguity — auto-promotion does not re-run the waterfall, excludes the candidate from its own pool, and applies the free-seat test to every waitlisted candidate — implementation.py:284-294
- §3.8 — insert — ambiguity — `origin_school_id` is null when the residence area has no live assignment — implementation.py:437-442
- §3.8 — insert — ambiguity — transfer filing never consults `implementation_status` — implementation.py:414-419
- §3.8 — revise — mismatch — `DENY` is reachable from `WAITLISTED` by an officer; `WAITLIST` on an already-waitlisted request → `ERR_TRANSFER_NOT_DECIDABLE` — implementation.py:500-522
- §3.8 — revise — ambiguity — window close neither consults nor changes `implementation_status` — implementation.py:343-346
- §4 (endpoint table) — revise — mismatch — PATCH `/schools/{id}` is not the only path to `MOTHBALLED`, and it is available in any study phase — setup.py:195-197, 241-259

Tests were used only as auxiliary cross-reference; every pin above is sourced from `implementation/`.

---

## Pipeline complete — 2026-09-02T20:02:30.000Z

Steps 1–9 all executed. Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 9 test files, 116 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ with results.{1..8}.json all at 116/116.
