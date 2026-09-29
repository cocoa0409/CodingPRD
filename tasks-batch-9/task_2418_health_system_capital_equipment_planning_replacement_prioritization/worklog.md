# Worklog — task_2418_health_system_capital_equipment_planning_replacement_prioritization

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2418_health_system_capital_equipment_planning_replacement_prioritization/` and its `workspace/` subdirectory. Index 2418 was pre-assigned by the invoking pipeline; no index scan or auto-allocation was performed (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-02T18:34:14.163374893Z

All three artifacts are complete and lint-clean.

## Generated — `/home/ubuntu/github/CodingPRD/tasks/task_2418_health_system_capital_equipment_planning_replacement_prioritization/`

**SCAFFOLD.yaml** (§1.0–§1.7, 172 KB) — `domain_name: health-system-capital-equipment-planning`, `api_prefix: /capital`, difficulty `expert_plus`, archetypes `quota_allocation` + `multi_party_negotiation`, layers `dual_variant_calculation` / `cascading_side_effects` / `optimistic_concurrency` / `rate_threshold_triggers`, topology `graph`, state-machine shape `parallel`, consistency `immediate`, role model `segregation_of_duties`.
- **14 entities**: Facility, Department, CapitalCycle, FacilityAllocation, EquipmentAsset, ServiceEvent, ReplacementRequest, PriorityScore, CommitteeMember, CommitteeVote, GpoContract, VendorQuote, InstallationProject, UtilizationAudit.
- **69 endpoints**, **8 calculations** (`asset_ruls_score`, `priority_composite_score`, `negotiated_capital_price`, `five_year_tco`, `facility_allocation_waterfall`, `request_funded_amount`, `committee_tally`, `business_case_variance` — each with constants, worked example and wrong-readings), **6 state machines**, **53 validations (V01–V53)** now listed in strict priority order, **61 error ids**, **5 roles**, **2 concurrency rules** (`vote-create-stale-request`, `allocate-supersede-stale-cycle`).
- Edit note: V19 (ERR_AUDIT_INVALID_STATE) sits at priority **51** — moved ahead of V15 (52) so a second `collect` is an audit-row fault, and its row was relocated in the table so the listing matches evaluation order.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — **24 instances / 529 calls**, 2 per hard-reasoning rule across the nine rule families (dual-variant divergence, pinned evaluation order, non-linear scoring, cyclic/parallel state, multi-hop cascades, priority ladders, exact boundaries, cross-entity dependencies, conservation round-trips).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — **101 instances (66 full recipes + 35 `excluded_because` stubs) / 954 calls** across all nine claim-extraction sections: entities 13, state_machines 12, calculations 11, validations 29, endpoints 5, errors 11, rbac 6, cross_cutting_complexity_layers 12, consistency_model 2. Every stub cites a §1.8 instance that exists by name; all names unique across both design files; **all 61 catalogued error ids are now triggered** by at least one §1.8/§1.9 instance (only the `ERR_XXX` envelope placeholder is unreferenced).

Lint (`scaffold_lint.py`, run from the task dir): 69 endpoints / 14 entities / 24 §1.8 / 66 §1.9 active instances / 1483 calls — `VERDICT: clean lint`.

## Step 3: Copy shared files — 2026-09-02T18:34:14.179408421Z

Copied `./INSTRUCTION.md` → `tasks/task_2418_health_system_capital_equipment_planning_replacement_prioritization/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T18:49:40.167794382Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **498 lines / 103,330 bytes**, ending at a real boundary (final row of the §5 table, `ERR_INSTALLATION_NOT_COMMISSIONED | 409`). The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Structure**

- §1 Introduction — 3 paragraphs (spreadsheet pain point; capital conservation + segregation of duties; `/capital` mount and role narrowness).
- §2 Global Specifications, 11 subsections: 2.1 User and Role-Based Access Control (5 roles, all `identity:` translations) · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Server Logical Clock · 2.5 Monetary Amounts, Score Precision and Rounding Discipline · 2.6 Record Identity, Timestamps and Versioning (including the three entities that carry neither `updated_at` nor `version`) · 2.7 Nested Path Resolution (all eleven NOT_FOUND ids + body-FK resolution) · 2.8 Optimistic Concurrency Control · 2.9 Segregation of Duties · 2.10 The Conserved Capital Identity · 2.11 Order of Rule Evaluation (52 ordered items covering all 53 validations with error id, status and `applies_to` scope).
- §3 Business Logic & Workflows, 11 subsections: 3.1 The Capital Estate · 3.2 Service History, Remaining Useful Life and the Derate Gate · 3.3 The Capital Cycle Stage Pipeline · 3.4 Replacement Request Intake, Revision and Screening · 3.5 Prioritization Scoring Across the Four Drivers · 3.6 Distributing the Pool: The Facility Allocation Waterfall and Contingency Reserves · 3.7 Committee Deliberation: Ballots, Quorum and the Chair's Decision · 3.8 Group Purchasing, Vendor Negotiation and the Negotiated Cost of Ownership · 3.9 Funding, the Commitment Cascade and Capital Release · 3.10 Installation Sequencing: Two Axes, Downtime and Go-Live · 3.11 Post-Implementation Utilization Audit and Asset Disposition.
- §4 API Endpoints — intro paragraph on 201-for-create / 200-for-modify plus the 4-column table, **69 rows** (verified count).
- §5 Error Code Catalogue — 2-column table, **61 rows** (verified count). No audit footer, no contract-report block.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 142 required, 142 present, 0 missing
- endpoints[].input / request_body: 103 required, 103 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing  (this scaffold expresses
  list filters as optional members of endpoints[].input, all of which are counted above)
- endpoints[].path_params: 0 required, 0 present, 0 missing  (all templated as {id})
- deduplicated union: 160 required, 160 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 53 checked, 53 expressed in prose (§2.11 renders them as a
  single 52-item ordered list; V03/V04 share item 3 and item 4 as the path-id and body-FK
  existence checks), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (operation + expected_request_version /
  expected_cycle_version + ERR_STALE_REQUEST_VERSION / ERR_STALE_CYCLE_VERSION + 412 all named,
  framed purely as stale-version with no temporal-overlap language), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (asset_ruls_score nominal+adjusted,
  priority_composite_score, negotiated_capital_price six steps, five_year_tco budgetary+negotiated,
  facility_allocation_waterfall PRO_RATA+RANK_ORDERED, request_funded_amount, committee_tally,
  business_case_variance), 0 missing
- validations[] conditions: 53 checked, 53 matchable to error_id in prose, 0 missing
  (all 61 error ids appear in §1–§3 narrative, not only in the §5 table)
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 142 checked, 142 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (PRO_RATA vs RANK_ORDERED; budgetary vs negotiated TCO;
  nominal vs adjusted RULS; counter vs revise; PASSED vs UNDERPERFORMING; approve/defer/reject bars;
  the two project state axes; TRADED_IN vs SCRAPPED; screen-pass vs screen-return), 9 with equal
  prose density, 0 asymmetric
Status: PASS
```

```
§3 path purity check:
- §3 spans lines 190–355; 997 backticked tokens, 301 distinct
- tokens starting with "/": 0
- bare HTTP-method tokens: 0
- method+path tokens: 0
- unbackticked slash-prefixed paths: 0
Status: PASS
```

**Notes for the caller:** two verification pitfalls hit during this run, worth reusing. (1) A naive backtick-token extraction over a PRD containing §2.2's two fenced JSON blocks flips backtick parity and produces a bogus "126 fields missing" result — fenced blocks must be stripped before the Contract 1 diff. (2) The scaffold gives `description` on only 3 of 69 endpoints (indices 0, 35, 45), so the §4 descriptions are authored rather than copied; the §5 table was trimmed back to the mandated 2 columns after an initial draft carried a third "Meaning" column.

**Orchestrator truncation guard (Step 4 post-check):** `grep` of `^#{1,3} ` shows §1 through §5 all present in order; `tail -15` ends on the complete final table row `| ERR_INSTALLATION_NOT_COMMISSIONED | 409 |`. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T21:13:13.913756861Z

Suite complete. Final file written and the whole suite re-audited.

## Files written (Stage 2, this session)
- `test_suite/test_15_access_ladder_write_scopes_and_duties.py` — 5 tests, the last five queue-B `rbac` instances: the identity → role → existence head of the ladder (401/401/200-empty/403/404); each role refused the other four roles' exclusive operations (six 403s, with a bogus body-borne `installation_project_id` proving rank 2 precedes rank 4); all five roles reading identical `GET` payloads on the same rows; department and facility write scopes outranking body shape and request state (`-5` volume still answers `ERR_DEPARTMENT_SCOPE_VIOLATION`, foreign director on a DRAFT request still answers `ERR_FACILITY_SCOPE_VIOLATION`); and the segregation-of-duties bar (`ERR_REQUEST_INVALID_STATE` while SCORED, then `ERR_SOD_ALLOCATOR_CANNOT_FUND`, then a clean draw by the second planner).

## Final suite state
- `test_helpers/` (9 modules, Stage 1) unchanged; `test_suite/` = 15 files, **116 tests**, all collected by pytest (`116 tests collected`).
- `python3 -m pyflakes test_suite/*.py` clean (the only pyflakes output is the intentional barrel re-export noise in `test_helpers/__init__.py`).
- Citation audit: `tests=116 problems=0` — every docstring is verbatim-greppable against `workspace/PRD.md`, rule-bearing, full-sentence, and ends in exactly one `Design:` line.
- Design audit: `tagged_tests=116 distinct_instances=90 problems=0`.
- No `skip`/`skipif`/`xfail` markers anywhere; no generated text mentions "scaffold".

## Instance accounting
- **Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`)**: 24 instances, all 24 translated, 50 tests (≥2 each) across `test_01`–`test_06`.
- **Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`)**: 66 non-stub instances, all 66 translated, 66 tests across `test_07`–`test_15`. 35 `excluded_because:` stubs not translated (by spec); all 35 `difficulty_instance:` pointers verified to resolve to real queue-A names.
- **Skipped for PRD-first failure: none.** Every non-stub instance had verbatim PRD coverage that uniquely derived its outcome.

## Corner-design divergences recorded (claim kept, PRD-derived figure asserted)
1. `Corner/errors/every_error_response_carries_the_same_two_field_envelope_across_status_classes` states HTTP 400 for `ERR_VALIDATION`; the PRD never mentions 400, so 422 is asserted (`test_08`).
2. `Corner/validations/deactivating_the_only_eligible_voter_…` replays a pre-vote `expected_request_version`, which §2.11 rank 21 answers with 412; the test reads the current version so `ERR_VOTE_CONFLICT_OF_INTEREST` (rank 33) is the uniquely-derived outcome (`test_12`).
3. Five instances assert `allocated_cents 500000000 / unallocated_cents 0` for a facility whose demand is 100000000 (`the_fund_response_is_already_the_post_cascade_state_…`, `the_cycle_counters_reconcile_…`, `a_re_allocation_needs_the_current_cycle_version_…`, `all_five_roles_share_every_get_on_the_same_rows`, `the_planner_who_allocated_the_cycle_cannot_fund_from_it`); §3.6 caps a facility grant at its own `demand_cents`, so 100000000 is asserted.
4. `Corner/rbac/the_planner_who_allocated_the_cycle_cannot_fund_from_it` claims a post-fund `available_cents 400000000` / posture `ACTIVE` / cycle still `ALLOCATED`; §3.9 derives `available_cents 0` and posture `EXHAUSTED`, which is what the test asserts.

**Orchestrator note on Step 5/6 concurrency (deviation, recorded for honesty):** the skill requires Steps 5 and 6 to be launched in a single assistant message so that impl-gen physically cannot see `test_suite/` (it would not yet exist). The orchestrator emitted only the Step 5 Agent call in that message, so Step 5 ran to completion first and `test_helpers/`+`test_suite/` were on disk when Step 6 started. Physical isolation was therefore replaced by an explicit prohibition: Step 6's prompt carried an ABSOLUTE HARD CONSTRAINT forbidding any read/list/glob/grep of `test_helpers/`, `test_suite/`, both design YAMLs, and sibling tasks. Step 6 reported on exit that "Test directories, the two design YAMLs, and sibling task directories were never read." Throughput was lost (sequential instead of parallel) but the PRD-only contract was preserved by instruction rather than by absence.

## Step 6: Generate implementation — 2026-09-02T21:13:13.926280541Z

The implementation is complete and verified.

## Module layout

`workspace/implementation/` (3,773 lines, 22 files):

- `start.sh` — installs `flask` only when missing (avoids boot contention under `--isolation per-test-server`), then `exec python3 app.py`; `requirements.txt`
- `app.py` — blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, one global `db.lock` per request via `before_request`/`teardown_request`, `app.run(host=0.0.0.0, port=$PORT|10000, threaded=True, use_reloader=False)`
- Core: `db.py` (in-memory dicts + logical clock, `_seq` insertion counter for `created_at ASC`, no seeding, no disk I/O), `errors.py` (53-entry catalogue), `response.py` (meta/response_type/data envelope, pagination inside `meta`), `middleware.py` (401 then 403), `validation.py` (typed field/query helpers, all ERR_VALIDATION), `numeric.py` (`Decimal` + ROUND_HALF_UP only), `serializers.py` (explicit per-entity field projections), `lookups.py` (per-entity 404s, filters, windowing)
- `routes/`: `clock`, `estate` (facilities/departments), `cycles` (cycles + allocations), `assets` (assets/service events/decommission), `requests` (intake→screen→vote→decision→fund), `members`, `gpo` (contracts + vendor quotes), `projects`, `audits`
- `services/`: `ruls`, `scoring`, `pricing`, `allocation`, `committee`, `cascades`

## Endpoint count

**69 of 69** — a programmatic diff of `app.url_map` against the SCAFFOLD roster shows zero missing and zero extra (method + path exact).

## Calculations and state machines implemented

- `adjusted_ruls` with the service-penalty derate gate and the replacement-eligibility gate
- `priority_composite` (safety/growth/regulatory/EOS drivers, department penalty, expedited flag) with PriorityScore history rows and cycle `scored_count`/`expedited_count` refresh
- `negotiated_capital_price` — six ordered steps (tier from list price, GPO discount, multi-unit addendum on the post-discount base, subtotal, trade-in credit capped against the subtotal, net)
- `five_year_tco` budgetary vs negotiated variants (escalation, warranty waivers, year-1 utilization ramp) and `baseline_year1_opex_cents`
- Waterfall allocation: PRO_RATA with FLOOR plus a 1-cent remainder sweep vs RANK_ORDERED single pass; facility contingency reserve, availability identity, posture/exhaustion, contingency release
- `committee_tally` — weighted quorum 3/5, approval 2/3, defer 1/2 by exact integer cross-multiplication, safety-officer veto short-circuit, ballot supersession
- `business_case_variance` — 80.00 attainment floor / 10.00 opex ceiling compared after 2-dp rounding, with the 3-hop underperformance cascade (audit → department penalty capped at 20 → re-score SCORED requests in SCORING/ALLOCATED cycles)
- State machines: cycle DRAFT→INTAKE_OPEN→SCORING→ALLOCATED→COMMITTED; request 11 states; asset lifecycle × disposition; cyclic quote negotiation SUBMITTED↔COUNTERED (round cap 3) with SUPERSEDED/WITHDRAWN; project's three parallel dimensions (construction × equipment × record) with the fork-join go-live; audit SCHEDULED→PASSED|UNDERPERFORMING
- Cross-cutting: optimistic concurrency (`expected_request_version`, `expected_cycle_version`), segregation of duties (allocator-cannot-fund, sponsor/conflicted/inactive/foreign-facility cannot vote, CHAIR-only close, SAFETY_OFFICER-only veto), 4-deep funding cascade with auto-commit + defer, buffered downtime conflict (24h, half-open), closed-interval construction capacity, predecessor DAG cycle detection, and the single-error precedence ordering from the V01–V53 priority table

## Boot verification

- Cold `bash start.sh` on three separate ports each answered HTTP 200 within ~1s with a completely empty store (`total_count: 0`), confirming clean per-invocation boot with no persistence.
- Happy-path sweep across all subsystems: **0 failures** (facility→department→asset→service event→cycle→request→submit→screen→score→allocate→4 ballots→decision APPROVED→fund→GPO contract→quote counter/revise/accept→project construction+equipment advance→go-live→audit create/collect→decommission TRADED_IN), including the auto-commit-on-exhaustion path.
- Corner sweep: **0 failures** across ERR_INVALID_INTERVAL, ERR_CONSTRUCTION_WINDOW_REQUIRED (both directions), ERR_FACILITY_SCOPE_VIOLATION, buffered ERR_DOWNTIME_WINDOW_CONFLICT plus its exact-boundary non-conflict, ERR_CONSTRUCTION_CAPACITY_EXCEEDED on merely-touching intervals, self- and two-hop ERR_PROJECT_DEPENDENCY_CYCLE, ERR_PREDECESSOR_NOT_COMMISSIONED, four ERR_PROJECT_INVALID_STATE variants, two ERR_AUDIT_WINDOW_INVALID variants, ERR_AUDIT_INVALID_STATE, ERR_DUPLICATE_KEY, tier-floor ERR_VALIDATION, ERR_NEGOTIATION_ROUND_LIMIT, ERR_QUOTE_INVALID_STATE, ERR_QUOTE_EXPIRED, ERR_PROJECT_ACTIVE, quote accept/withdraw funded-amount round trip (100000000 → 76800000 → 100000000).
- Committee sweep: **0 failures** — sponsor/inactive ERR_VOTE_CONFLICT_OF_INTEREST, ERR_VETO_NOT_PERMITTED, ERR_STALE_REQUEST_VERSION, ERR_CHAIR_REQUIRED, ERR_QUORUM_NOT_MET, veto→REJECTED without consulting quorum, and re-voting superseding (4 live ballots, not 8) → APPROVED.
- Infrastructure checks: unknown path 404, wrong method 405, missing `X-User-ID` 401, malformed JSON 422, and repeated requests after each showing no lock deadlock.

Test directories, the two design YAMLs, and sibling task directories were never read.

## Step 7: Run tests and iterate — 2026-09-02T21:28:40.880690921Z

Clean sweep confirmed on disk.

## Summary

**Iterations run:** 2 (sweep 1: 108/116 in all 8 rounds, 8 deterministic failures; sweep 2: 116/116 in all 8 rounds).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence that uniquely determined the outcome — all 8 failures were test-side mis-translations of PRD, not PRD silence.

**Fixes applied to `test_helpers/`:** none — no fixture/factory/header helper was at fault. (The one helper-shaped bug lived in a per-file helper inside `test_suite/`; see below.)

**Fixes applied to `implementation/`:** none. Three failures were cases where the implementation was already the PRD-faithful reader and the test contradicted it (see items 4, 6, 8).

**Fixes applied to `test_suite/`:**

1. `test_02_cost_of_ownership_and_vendor_negotiation.py` lines ~253/281/486 — three `validate_success(api.create_quote(...))` calls omitted the expected status, so the default 200 tripped against the created quote's 201. Passed `201` explicitly. PRD §4: *"Creation calls answer with HTTP 201 and the created resource."*
2. `test_09_condition_thresholds_and_score_drivers.py` `_scanner()` — passed `oem_support_end_date` positionally-as-keyword *and* forwarded `**overrides`, raising `TypeError: got multiple values`. Rewrote as a defaults dict updated by `overrides` (same pattern as `test_helpers/factories.py`), so per-test EOS dates override cleanly. Verified the test's expected 60.00/0.00 drivers and 51.69/39.69 composites are exactly what PRD §3.2/§3.5 yield.
3. `test_10_..._request_lifecycle.py` `test_the_second_bid_on_one_scanner_...` — the setup created *both* draft requests before submitting the first, so submitting option A was correctly rejected: PRD §3.4 says *"no other request naming the same `asset_id` in the same `cycle_id` may hold a status other than `WITHDRAWN`, `REJECTED` or `DEFERRED`"*, and a `DRAFT` sibling holds such a status. Moved option B's creation to after option A's submit; the asserted `ERR_DUPLICATE_ASSET_REQUEST`-then-withdraw-then-succeed rule is unchanged.
4. `test_10_...` `test_a_repeated_facility_code_..._duplicate_key` — the "twin" facility used `code="NRH-2"`, but PRD §3.1 restricts `code` to *"uppercase letters A through Z and the digits 0 through 9"*, so the server correctly answered `ERR_VALIDATION`. Changed to `NRH2` (and the follow-up equality assert).
5. `test_13_allocation_reruns_and_funding_capacity.py` `test_replaying_the_version_that_just_allocated_...` — asserted the patched facility's `version == 2`; PRD §3.1 says asset registration *"increments the owning facility's `active_asset_count` and bumps that facility's `version`"*, so the fixture's asset already took it to 2 and the planner edit lands on 3. Corrected to 3.
6. `test_13_...` `test_a_withdrawal_re_derives_both_scored_counters_...` — asserted `expedited_count == 0` after withdrawing the expedited request. PRD §3.3 defines it as *"the number of the cycle's requests whose `expedited` flag is currently true"* — no status restriction, and no PRD sentence clears `expedited` on withdrawal — deliberately contrasted with `scored_count` (*"requests that stand in `SCORED`"*). Corrected to 1; `scored_count == 1` and the cycle version bump assertions were already faithful and kept.

No assertion was weakened: no `error_id` was downgraded to an HTTP-status check, no `skip`/`xfail` added, and no boundary was approximated.

**Orchestrator independent verification of the Step 7 sweep (per standing guidance that a Step 7 subagent can claim a clean sweep without leaving artifacts):** `ls` + `json.load` over `workspace/implementation/results.{1..8}.json` — 8 files present, all timestamped 21:25, each reporting `passed 116 / total 116`. Clean sweep confirmed by the orchestrator, not merely asserted by the subagent.

**Note on the Step 7 summary's internal inconsistency:** the subagent's "Fixes applied to `implementation/`: none" line cross-references "items 4, 6, 8" while its numbered list has only 6 entries; the numbering drifted during editing. The substantive claim — zero `implementation/` edits, zero deletions, six `test_suite/` corrections — is consistent with the rest of the entry and with the on-disk state, so the stale item numbers are left as-written rather than silently rewritten (worklog is append-only and verbatim).

## Step 8: Finalize PRD — 2026-09-02T21:31:42.316676398Z

`PRD_FINALIZED.md` is a **verbatim copy** of `PRD.md`. Every item in `<step_7_diff>` traced to a test-side mis-translation of a PRD sentence that already uniquely determines the implementation's behavior; no PRD silence and no PRD/impl mismatch survived verification.

## Line counts

- `PRD.md`: 498 lines. `PRD_FINALIZED.md`: 498 lines. Delta: **0 lines, 0.00%** (`diff` reports the files identical).

## Changes

None. No edit was emitted, so there is no per-change bullet list. Below is the per-item adjudication that produced the empty edit set (subject identified + impl paths enumerated for each, i.e. the mandatory (a)/(b) log; (c) is vacuous because no wording was committed).

**Item 1 — quote-creation HTTP status (test passed no explicit 201).**
(a) Subject: status code of creation endpoints. (b) Enumerated every `created_response` callsite in `implementation/routes/*.py` — `estate.py:49,111`, `cycles.py:63`, `assets.py:80,177`, `requests.py:131,370`, `members.py:43`, `gpo.py:73,209`, `projects.py:158`, `audits.py:69`; `response.py:41-42` maps `created_response` → 200-envelope with code 201. All POST-create endpoints uniformly answer 201 and every non-create POST uses `object_response` (200). PRD §4 line 358 already states this verbatim. Test-side bug → no edit.

**Item 2 — `_scanner()` `TypeError` in a per-file test helper.**
(a) Subject: EOS driver / EOS penalty and the composite arithmetic the fixed test asserts. (b) Read `services/ruls.py:70-90` (EOS penalty vs. `ruls_as_of`, 365-day imminent band) and `services/scoring.py:61-76` (EOS driver vs. `plan_year_start`, 730-day horizon, single rounding of the weighted sum, penalty subtracted post-weighting). Both match PRD §3.2 line 208 and §3.5 lines 258-260 exactly; the asserted 60.00/0.00 drivers and 51.69/39.69 composites fall out of the PRD text. Pure keyword-collision bug in the test file → no edit.

**Item 3 — duplicate-asset-request fixture ordering.**
(a) Subject: the live-sibling set on request submit. (b) Read `routes/requests.py:27` (`LIVE_SIBLING_EXCLUDED = ("WITHDRAWN","REJECTED","DEFERRED")`) and `:250-258` (sibling scan over same `cycle_id` + `asset_id`, excluding self, raising `ERR_DUPLICATE_ASSET_REQUEST`), plus the surrounding guard order `:235-261` against §2.11 ranks 12/13/14/16/22/23/24. Impl excludes exactly the three statuses PRD §3.4 line 236 names, so a `DRAFT` sibling is a conflict — PRD determines it. Fixture-ordering bug → no edit.

**Item 4 — facility `code="NRH-2"`.**
(a) Subject: facility `code` charset/uniqueness. (b) Read `routes/estate.py:20,30-39` (`^[A-Z0-9]{2,8}\Z` → `ERR_VALIDATION`, then duplicate-code scan → `ERR_DUPLICATE_KEY`) and `routes/estate.py:57-59` (patch does not accept `code`, so the charset rule has no second callsite). PRD §3.1 line 194 already pins "uppercase letters A through Z and the digits 0 through 9". Test payload bug → no edit.

**Item 5 — facility `version == 2` vs `3`.**
(a) Subject: facility `version` bumps. (b) Enumerated every writer of a facility row: `routes/estate.py:67` (patch), `routes/assets.py:78-79` (asset registration increments `active_asset_count` + `touch`), `routes/assets.py:223-226` (decommission decrements + `touch`). All three are already described — §3.1 line 198 for registration, line 194/§4 for the patch, §3.11 line 354 for decommission — and §2.6 line 101 covers side-effect version increments. Test arithmetic bug → no edit.

**Item 6 — `expedited_count` after withdrawing an expedited request.**
(a) Subject: definition and refresh sites of `scored_count` / `expedited_count`, and whether any path clears `expedited`. (b) Enumerated: `services/scoring.py:130-152` (`refresh_cycle_counts` — `scored_count` filters `status == "SCORED"`, `expedited_count` filters `req["expedited"]` with no status filter), `routes/requests.py:302-308` (withdraw sets status only, then `refresh_cycle_counts(..., bump=True)`; `expedited` is never reset), `services/scoring.py:120-127` (`expedited` written only by a score append), `services/cascades.py` / `routes/cycles.py` refresh callers, and every other assignment to `expedited` (`grep` shows only request creation at `routes/requests.py:122` and `scoring.py:126`). This exactly mirrors PRD §3.3 line 226 ("requests that stand in `SCORED`" vs. "whose `expedited` flag is currently true") and §3.4 line 242. Impl was the PRD-faithful reader; test expectation was wrong → no edit.

## Note

Step 7's own report states no `implementation/` fix, no `test_helpers/` fix and no test deletion — i.e. it found no PRD-silence, and the three impl-vs-test contradictions resolved in the implementation's favour on verbatim PRD sentences. My independent read of the enumerated impl paths agrees, so the correct Step 8 output is the unmodified copy.

**Orchestrator verification:** `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` exits 0 — the two files are byte-identical, as the subagent reported. Step 8 was run rather than skipped because Step 7 recorded six `test_suite/` fixes (the skip condition requires zero fixes in every layer); the correct outcome for a Step 7 diff composed purely of test-side bugs is an unmodified copy, which is what landed.

## Step 9: Complete PRD — 2026-09-02T21:47:05.314311717Z

PRD_COMPLETED.md is written. Summary below.

## Files

- Source: `workspace/PRD_FINALIZED.md` — 498 lines, 102,925 chars (103,330 bytes); verified byte-identical to `PRD.md`.
- Output: `workspace/PRD_COMPLETED.md` — **498 lines** (unchanged), **108,641 chars** → **char-delta +5,716**. 38 lines touched; no new lines, paragraphs or sections; all 134 markdown table rows preserved with identical column counts.

## Counts

- **Ambiguity-pins (PRD was silent): 24**
- **Mismatch-revisions (PRD described behavior impl does not exhibit): 18**
- Total edits: 42, each applied by exact-unique-match replacement with a fail-fast assertion.

## Changes

- §2.1 — revise — ambiguity — an absent `X-User-Role`, or one naming a role outside the five, is `ERR_UNAUTHORIZED` 403, not a separate fault — `implementation/middleware.py:28`
- §2.1 — insert — ambiguity — a `CommitteeMember` whose `X-User-ID` names no member row gets `ERR_MEMBER_NOT_FOUND` 404 at rank 3, ahead of body validation and all state checks — `implementation/routes/requests.py:329`
- §2.2 — insert — ambiguity — `api_request_id` is literally `req_` + 16 lowercase hex chars, minted per call and never echoed from the caller — `implementation/response.py:24`
- §2.3 — insert — ambiguity — filters are exact equality (never prefix/substring); an unparseable filter value matches no row rather than 422; undeclared query params are ignored — `implementation/validation.py:189`
- §2.4 — revise — mismatch — "Nothing in this system reads wall-clock time" narrowed to "no domain comparison", because record-keeping stamps do — `implementation/db.py:72`
- §2.4 — insert — ambiguity — `created_at`, `updated_at` and `api_request_timestamp` come from real wall time and survive clock jumps; the clock endpoint requires `now` and echoes `{"now": <as written>}` — `implementation/routes/clock.py:20`
- §2.5 — insert — ambiguity — two-decimal score/percentage fields serialize as JSON numbers (`85.0`), not fixed-width strings — `implementation/response.py:12`
- §2.6 — insert — ambiguity — every PATCH is partial: an explicit JSON `null` counts as absent, so no optional reference can ever be cleared; a no-op PATCH still bumps `updated_at`/`version` — `implementation/validation.py:47`
- §2.11 rank 16 — insert — ambiguity — `ERR_REQUEST_INVALID_STATE` also guards quote accept, quote withdraw and go-live, but is read *after* those endpoints' rank-18/19 tests — `implementation/routes/gpo.py:292`
- §3.2 — revise — mismatch — an asset edit propagates re-scores on every write; only a service-event append is gated on the derate flip — `implementation/routes/assets.py:115` vs `implementation/routes/assets.py:173`
- §3.2 — revise — mismatch — cycle `version` bumps on a cascade only when `scored_count` or `expedited_count` actually moves, not on every re-score — `implementation/services/scoring.py:150`
- §3.5 — revise — mismatch — `ASSET_CONDITION_CHANGE` is stamped on every asset edit, and on a service-event append only when the gate flips — `implementation/routes/assets.py:172`
- §3.5 — revise — mismatch — the cascade refreshes both cycle counts (not just `expedited_count`) and bumps cycle `version` only on a real change — `implementation/services/cascades.py:33`
- §3.3 — revise — mismatch — removed `ALLOCATED` from the close-voting stage gate: the chair's decision consults no cycle stage at all — `implementation/routes/requests.py:393`
- §3.4 — insert — ambiguity — a new request is born with `budgetary_operating_5y_cents`, `budgetary_tco_cents`, `baseline_year1_opex_cents` at 0 (not null) and both `negotiated_*` null — `implementation/routes/requests.py:150`
- §3.4 — insert — ambiguity — a `DECOMMISSIONED` asset at submit reports `ERR_ASSET_NOT_REPLACEMENT_ELIGIBLE`, not an asset-state fault — `implementation/routes/requests.py:247`
- §3.7 — revise — mismatch — deleted the requirement that a non-`SUPERSEDED` allocation row exist to ballot; no allocation is read by a vote — `implementation/routes/requests.py:335`
- §3.7 — insert — ambiguity — veto presence reads `seat` on the member row at tally time; unlike `counted_weight` it is not pinned on the ballot — `implementation/services/committee.py:63`
- §3.8 — insert — ambiguity — a contract PATCH re-checks the strict floor ordering on the resulting effective pair, rejecting with `ERR_VALIDATION` — `implementation/routes/gpo.py:96`
- §3.8 — revise — ambiguity — quote accept: `ERR_QUOTE_INVALID_STATE` runs ahead of all other state tests; the request-state fault is `ERR_REQUEST_INVALID_STATE` — `implementation/routes/gpo.py:288`
- §3.8 — insert — ambiguity — all four accept-time trade-in failures (including "not the request's own asset") collapse to `ERR_TRADE_IN_ASSET_UNAVAILABLE`; `ERR_TRADE_IN_ASSET_MISMATCH` is creation-only — `implementation/routes/gpo.py:301`
- §3.8 — revise — ambiguity — the two accept allocation faults are reachable only when the request already stands in `FUNDED`; an `APPROVED`-only accept still rewrites `funded_amount_cents` — `implementation/routes/gpo.py:322`
- §3.8 — revise — ambiguity — quote withdraw: `ERR_QUOTE_INVALID_STATE` first, then `ERR_REQUEST_INVALID_STATE` — `implementation/routes/gpo.py:367`
- §3.8 — insert — ambiguity — withdraw's allocation faults arise only when the withdrawn quote was the accepted one and the request stands in `FUNDED` — `implementation/routes/gpo.py:380`
- §3.9 — insert — ambiguity — withdraw-funding checks `ERR_PROJECT_ACTIVE` before the allocation lookup, and a missing usable row yields `ERR_NO_FACILITY_ALLOCATION` — `implementation/routes/requests.py:460`
- §3.10 — revise — ambiguity — go-live's owning-request test is read after both axis checks and yields `ERR_REQUEST_INVALID_STATE` — `implementation/routes/projects.py:317`
- §3.11 — insert — ambiguity — a zero pinned `baseline_year1_opex_snapshot` (or zero volume projection) is divided by 1 — `implementation/routes/audits.py:89`
- §4 preamble — insert — ambiguity — pinned which single row each multi-row operation returns (cycle stages → cycle, release-contingency → allocation, fund/withdraw-funding → request, decommission → asset, quote ops → quote, project ops → project, collect → audit) — `implementation/routes/cycles.py:149`
- §4 — revise — mismatch — PATCH facility: "rank order" replaced with the real editable set (`name`, `region`, ceiling); `code` is fixed — `implementation/routes/estate.py:57`
- §4 — revise — mismatch — facilities list filters are `region` and `code`, not "region code and site type" — `implementation/routes/estate.py:81`
- §4 — revise — mismatch — POST department takes name + modality scope, not "projected annual volume and strategic weighting" — `implementation/routes/estate.py:92`
- §4 — revise — mismatch — PATCH department edits only `name` and `modality_scope`, not "strategic weight and service-line code" — `implementation/routes/estate.py:113`
- §4 — revise — ambiguity — department list filters named exactly (`facility_id`, `modality_scope`, `underperformance_flag`) — `implementation/routes/estate.py:135`
- §4 — revise — mismatch — POST cycle takes a plan-year start, not an "intake window" — `implementation/routes/cycles.py:30`
- §4 — revise — mismatch — PATCH cycle edits pool, contingency fractions and plan-year start while in `DRAFT`; no "descriptive attributes", no "intake window" — `implementation/routes/cycles.py:62`
- §4 — revise — ambiguity — cycles list also filters by `allocation_method` — `implementation/routes/cycles.py:112`
- §4 — revise — mismatch — the score run leaves the cycle in `SCORING` (self-transition) and re-scores already-scored requests; it does not "move" the cycle there — `implementation/routes/cycles.py:130`
- §4 — revise — mismatch — PATCH asset has no editable recall flag; the real editable set is listed — `implementation/routes/assets.py:82`
- §4 — revise — mismatch — assets list has no recall-flag filter — `implementation/routes/assets.py:129`
- §4 — revise — mismatch — service-events list filters on `category` only; no "vendor-attended flag" — `implementation/routes/assets.py:185`
- §4 — revise — mismatch — PATCH request does not recompute the budgetary cost of ownership; that projection runs at submit — `implementation/routes/requests.py:264`
- §4 — revise — mismatch — requests list has no `facility` filter — `implementation/routes/requests.py:216`
- §5 preamble — insert — ambiguity — three framework-level identifiers outside the catalogue: `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500; malformed JSON is the catalogued `ERR_VALIDATION` 422 — `implementation/app.py:56`

## Notes

- Verified-and-deliberately-left-alone (PRD and impl already agree, so no edit): the §2.11 rank orders on request submit / screen / fund / quote create / allocate; the six-step quote pricing and its tier selection; five-year TCO per-year rounding and the 12/24-month warranty waivers; the growth-driver `denominator = current if current > 1 else 1` equivalence; `exhausted_allocation_count = 0` on a fresh allocation run; PRO_RATA floor division plus the one-cent rank-order sweep; the negotiation-round limit living on revise only (`negotiation_round > 3`); rank 6's facility-scope endpoint list excluding project cancel.
- Two §2.11 claims are unreachable rather than wrong and were left as written: rank 11 (`ERR_ASSET_DEPARTMENT_MISMATCH` "on request patch") and rank 10 (`ERR_ASSET_FACILITY_MISMATCH` "on asset patch") — neither `asset_id` nor `department_id` is editable, so the checks can never fire.
- Tests were used only as auxiliary cross-reference; no assertion was treated as authority, and `SCAFFOLD*.yaml` / `worklog.md` were not read.

**Orchestrator verification:** `PRD_COMPLETED.md` is 498 lines / 109,089 bytes (vs 103,330 for the source — the subagent's char figures are computed without the trailing-newline accounting, hence the small discrepancy against `wc -c`; the +5.7 KB magnitude agrees). §1–§5 all present in order, file ends on the complete final table row `| ERR_INSTALLATION_NOT_COMMISSIONED | 409 |`. Table integrity re-checked programmatically: §4 keeps 70 pipe-rows (header + 69 endpoints) at 5 pipes each and §5 keeps 62 pipe-rows (header + 61 errors) at 3 pipes each — identical to the source, so no table was corrupted by the 38 in-place line edits. `implementation/` and `test_suite/` were untouched by Steps 8–9, so Step 7's verified 8/8 × 116/116 sweep remains the standing result.

Pipeline complete: Steps 1–9 all executed, `workspace/PRD_COMPLETED.md` written.
