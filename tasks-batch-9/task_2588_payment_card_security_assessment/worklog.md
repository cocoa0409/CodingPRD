# Worklog — task_2588_payment_card_security_assessment

## Step 1: Create task directory — 2026-09-03T15:11:46.532Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate Scaffold — 2026-09-03T17:07:05.663Z

All three scaffold artifacts for task 2588 are complete and lint-clean.

## Final state

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD.yaml` | **3336** |
| `/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **2414** |
| `/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD_CORNER_DESIGN.yaml` | **4417** |

All three parse as YAML; `SCAFFOLD.yaml` has 13 top-level §1.0–§1.7 keys and contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the other two each have exactly one top-level key. `tail -20` on each confirms a clean structural boundary (a closing `assert:` list item / `shared_operations` list), not a truncated key.

## Work completed this session (final two §1.9 sections)

`cross_cutting_complexity_layers` — one group covering all four declared layers:
- `layer_optimistic_concurrency_on_worksheet_creation` (full recipe): a requirement `version` read while IN_TESTING goes stale when the conclusion lands, so `POST /requirement-assessments/{id}/ccws` answers **412 ERR_STALE_REQUIREMENT_VERSION** (the last previously-uncovered §1.6 id), then the byte-identical retry with the refreshed version returns 201 with `rigor_score == 71.25`.
- `layer_rate_threshold_flips_reassessment_at_the_third_qualifying_change` (full recipe): six change-log entries prove the filtered counter (APPLICATION_UPDATED with `affects_scope: true` and SEGMENT_RECLASSIFIED with `affects_scope: false` both do not count), the inclusive threshold of 3, `reassessment_due_date == 2026-10-30` (clock + 90) on the flip, and that a fourth qualifying entry after the clock advances does **not** push the date back out.
- Three `excluded_because:` stubs delegating the engagement-row OCC, the five-link cascade and the dual-variant arithmetic to their §1.8 owners.

`consistency_model` — `consistency_every_cascade_effect_is_visible_in_the_triggering_response` (`immediate`): a single segmentation FAIL verdict returns `segmentation_status == FAILED` in its own body, and the *first* read afterwards already shows posture RESTRICTED, `open_gap_count 1`, plan STALE, requirement back in IN_TESTING/GAP_OPEN and one OPEN remediation item — no polling window, and the two engagement projections are never transiently divergent.

## §1.9 coverage

Nine sections in guide order, **72 instances (54 full recipes + 18 `excluded_because:` stubs)**: entities 13, state_machines 10, calculations 12, validations 9, endpoints 5, errors 10, rbac 7, cross_cutting_complexity_layers 5, consistency_model 1. Every one of the 69 real `ERR_*` ids in §1.6 is now exercised by §1.8 or §1.9 (the only unmatched token is the `ERR_XXX` placeholder inside the §1.2 response-envelope example).

## Linter verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1083

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was listed, globbed, grepped or read at any point; the scaffold was derived solely from the scenario text and the generator skill's own specification.

## Step 3: Copy Shared Files — 2026-09-03T17:07:05.663Z

Copied `./INSTRUCTION.md` to `tasks/task_2588_payment_card_security_assessment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T17:23:44.326Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/workspace/PRD.md` — **477 lines**, built incrementally (one `Write` + 11 `cat >>` heredoc appends, none near the output cap). The file ends at a real boundary: the last line is the final row of the §5 error table (`| \`ERR_ASSESSMENT_BUDGET_EXCEEDED\` | 422 |`), not mid-sentence.

**Structure**
- `## 1. Introduction` — 3 paragraphs
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections (2.1 RBAC / 2.2 verbatim response envelope / 2.3 pagination / 2.4 identity+timestamps+`version` / 2.5 logical clock / 2.6 engagement posture gate / 2.7 scope partition and cascades / 2.8 OCC / 2.9 arithmetic and rounding / 2.10 the 14-rung validation ladder / 2.11 referential coherence)
- `## 3. Business Logic & Workflows` — 9 subsections, domain-narrative grouped (registries -> commissioning -> CDE boundary -> segmentation proof + cascade A -> sampling/fee/scope-lock -> requirement programme + cascade B -> CCWs, gap ledger, remediation + cascades C/D -> the ROC lifecycle -> quarterly scanning, disputes + cascade E, change log, reassessment)
- `## 4. Endpoint Definitions` — intro paragraph fixing 201-vs-200 semantics + **69 rows**, exactly 4 columns (Method, Path, Description, Authorized Role(s))
- `## 5. Error Code Catalogue` — **69 rows**, exactly 2 columns (Error ID, HTTP Status Code)

**Hard Contract 1 — Field-Name Coverage: PASS.** 151 unique entity field names + 12 endpoint-only identifiers = 163 required names. Two independent verification passes over PRD.md with fenced code blocks stripped: (a) token-in-backtick-span match -> 0 missing; (b) stricter exact-span match requiring the literal name for all 176 entity field entries across all 14 entities -> 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 69 error IDs appear in the §1–§3 prose (not merely in the §5 table) — verified programmatically, 0 missing. All 9 calculations are expressed in prose, including all 3 dual-variant ones (`component_sample_allocation`, `facility_sample_selection`, `compliance_projection`) with both variants stated. All 52 transitions across the 10 state-machine dimensions are covered: 38 carry explicit `FROM -> TO` arrow notation, and the remaining 14 are stated in equivalent prose, each individually re-read and confirmed. Both concurrency rules, all 6 roles, all 14 validation rungs, the 5 cascade chains and the 3 conserved-quantity invariants are present.

**Hard Contract 3 — §3 Path Purity: PASS.** Zero slash-paths, zero bare HTTP method tokens in §3. The same scan run across §1 and §2 also returns clean — paths and methods appear only in the §4 table.

**Style checks:** no pseudocode; the only fenced blocks are the two `json` envelopes inside the verbatim §2.2 contract. No numeric hedging. No Hard-Contract or scaffold-provenance text leaked into the document.

**Hard constraint honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point; every fact in the PRD derives from `SCAFFOLD.yaml` alone.

**Scaffold gaps resolved by documented editorial choice**: evidence append is gated on `test_status` `IN_TESTING` with `ERR_INVALID_REQUIREMENT_STATE`, since that error's `applies_to` names evidence creation but the entity carries no state gate; the evidence uniqueness triple (`procedure_ref`, `evidence_type`, `component_id`) is stated descriptively because the catalogue has no code for it; `facility_type`'s embedded rank is declared descriptive-only because `facility_sample_selection` orders strictly by `facility_name` ascending; and scope lock's "latest plan must be `ACTIVE`" precondition is stated with a `STALE` plan surfacing as `ERR_ENGAGEMENT_RESTRICTED`. No error codes were invented in any of these cases.

**Orchestrator verification (anti-truncation check):** independently ran `wc -l` (477), `tail -25` (ends on the final `ERR_ASSESSMENT_BUDGET_EXCEEDED` table row) and `grep -n '^## '` (all five sections present at lines 3/11/167/327/403). PRD is NOT truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T18:14:00.000Z

The implementation is complete, verified against the scaffold, and smoke-tested end to end.

## Files generated

`/home/ubuntu/github/CodingPRD/tasks/task_2588_payment_card_security_assessment/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded pip install + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 71 | 8 blueprints, `app.json.sort_keys = False`, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 146 | in-memory `Store` (14 dicts), logical clock defaulting to `2026-08-01T00:00:00Z`, ISO helpers, insertion-order tie-break |
| `errors.py` | 106 | 69-entry `ERROR_CATALOG` + `ApiError` |
| `response.py` | 72 | envelope, `req_<20>` ids, pagination meta |
| `middleware.py` | 302 | auth/role gate, typed validators, filters, pagination, ownership guards |
| `services/calc.py` | 209 | all Decimal algorithms |
| `services/derive.py` | 388 | computed fields, posture, scope forest, cascade helpers |
| `services/serialize.py` | 302 | explicit per-entity field lists |
| `routes/registry.py` | 178 | assessors, ASV vendors, `/_clock/set_current_utc` |
| `routes/engagements.py` | 284 | engagement lifecycle, QA assignment, scope lock, reassessment plan |
| `routes/segments.py` | 326 | scope forest, segmentation testing (cascade A), components |
| `routes/sampling.py` | 140 | dual-variant stratified sampling + re-pricing |
| `routes/requirements.py` | 234 | requirements, evidence, conclusions (cascade B) |
| `routes/ccws.py` | 286 | worksheets (cascade C), remediation ledger (cascade D) |
| `routes/rocs.py` | 222 | report drafting, QA, attestation, submission |
| `routes/scans.py` | 314 | scan cycles, findings, disputes (cascade E), change log |

3591 lines total. `python3 -m py_compile` passes on every `.py`; `__pycache__` cleaned up.

## Verification performed

- **Route coverage**: all 69 scaffold endpoints registered, exact paths/methods, no extras.
- **Algorithm worked examples — 100% match** by direct call into `services/calc.py`: 9/9 `ccw_rigor_score`, 7/7 `assessment_fee_total`, 3/3 `component_sample_allocation` + `coverage_ratio`, 4/4 `facility_sample_selection`.
- **Six live smoke suites** (server on port 18317, killed by PID only) exercised: envelope/meta shape, pagination `has_more`, clock control, certification/approval lapse derivation, the 3-day lead window cooldown, SoD/QA-qualification/lapsed-cert refusals, segment cycle + self-cycle, cross-engagement refs, withdraw guards, duplicate constraints, empty population, hostname-ASC sample selection, budget ceiling, all five cascade chains (A: FAIL expansion -> plan STALE -> re-plan keeps expansion -> PASS restores; B: gap minting; C: 4-link CCW accept; D: retest FAIL/PASS; E: rejected dispute reverting requirement 11.3.1), both OCC endpoints, posture FROZEN vs RESTRICTED precedence, independence violation (QA acting as `Assessor` to collect evidence, then blocked at decision), thin-control cap, monitoring ceiling, signature verbatim match, and the change-log threshold flipping `reassessment_due_date` to clock + 90 days (`2026-10-30`).
- **Fresh-boot cleanliness**: a newly launched process answers `GET /engagements` with `total_count: 0` — no seeded data anywhere.

## Notes on judgment calls

- `app.run(..., threaded=True)` matches Flask's own default; `threaded=False` risked keep-alive stalls under the per-test-server harness.
- Lead-ownership is enforced on `POST /engagements/{id}/sampling-plans` and `/scan-cycles` even though the priority-6 `applies_to` list omits them, because PRD §2.1 and the RBAC matrix both state every lead-only operation requires the `X-User-ID` match.
- `effective_class` is keyed on the persistent `scope_expanded_by_failure` marker rather than the `FAILED` status, so re-planning a failed zone does not prematurely release its subtree from the CDE (PRD line 215).
- Scope lock with no FINAL+ACTIVE plan answers `ERR_SAMPLING_PLAN_STALE`; only `estimated_hours`/`assessment_fee_total` and the ROC's frozen projection are stored, everything else is computed on read.

## Step 5: Generate Unit Tests — 2026-09-03T18:24:00.000Z

Stage 5 is complete. Both directories are at the task root (nothing under `workspace/`).

**Output**

`test_helpers/` — 9 modules, 3,102 lines: `__init__.py` (132), `api_client.py` (532, one method per PRD route plus `not_found_probe_paths`), `api_errors.py` (194, all 69 `ERR_*` ids + the HTTP-status map registered via an autouse fixture), `assertions.py` (338), `constants.py` (274), `factories.py` (448), `fixtures.py` (732, step helpers + 12 scenario builders + 10 pytest fixtures), `test_users.py` (120, identity-threaded headers), `types.py` (332).

`test_suite/` — `conftest.py` (37) plus 13 test modules, 9,146 lines total, **132 test functions / 133 collected cases**:
test_01 sampling variants & fee (700), test_02 compliance & rigor (609), test_03 segment/requirement states (664), test_04 cascades & gap ledger (735), test_05 gates & calendar (857), test_06 entities (639), test_07 state machines (573), test_08 calculations (675), test_09 validations (751), test_10 endpoints (519), test_11 errors (1,255), test_12 rbac (604), test_13 layers & consistency (528).

**Verification (all green)**
- `python3 -m py_compile` over every generated `.py`: OK. Each test module also imports cleanly with `PYTHONPATH=.`.
- `pytest --collect-only`: 133 tests; `pytest --setup-plan`: every fixture resolves, no errors.
- Machine audit of design tags, citations and coverage: **49 `Design: Difficulty/...` + 83 `Design: Corner/...` lines, exactly one per test**, every tag resolving to a real non-stub instance; all 18 difficulty instances have >=2 tests and all 54 non-stub corner instances have >=1; the 18 `excluded_because:` stubs are untranslated. Every `PRD:` citation was verified as a byte-exact (whitespace-normalised) substring of `workspace/PRD.md`. No occurrence of "scaffold" or section-number references, and no skip/xfail/mock/placeholder anywhere.

**Key PRD-first decisions worth relaying**
- The design indices repeatedly write `certification_status == EXPIRED`; the PRD only ever derives `ACTIVE` or `LAPSED`, so tests assert `LAPSED` (vendor `effective_approval` legitimately uses `EXPIRED`).
- Two yaml rigor scores (71.25 / 52.00) mis-derive the risk offset for R1; the PRD's "100 minus 15 per risk point" plus its own R6/R3 worked examples give 73.75 / 54.50, which is what the tests assert.
- Dropped, not weakened, as unbackable by the PRD: `last_validated_at` stamping on a `FAIL` verdict; `unmet_requirement_count` on the engagement read; `evidence_type_coverage` including an INSUFFICIENT technique; the clock body's exact key set; `RocReport.qa_reviewer_assessor_id` and `raw_finding_count` (no such fields); `NetworkSegment.engagement_id`; "no PATCH/DELETE on evidence items"; compliance percentages on a zero denominator. Two ladder probes were re-staged (low-severity dispute, foreign-vendor dispute) so the intended rung is the uniquely-derivable one rather than being outranked by a cycle-status rung.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both confirmed present directly under the task root, not under `workspace/`.

## Step 7: Run Tests and Iterate — 2026-09-03T18:53:00.000Z

Clean sweep: **133/133 in all 8 parallel rounds**, zero failures, zero errors.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Round 1: 114/133 in all 8 rounds. Round 2: 132/133. Round 3: 133/133 in all 8 rounds.

**Flakiness:** none observed. Every failure was bit-identical across all 8 rounds in every sweep, so no timing-sensitive or load-induced defects surfaced.

**Tests deleted:** none. All 133 collected cases remain; the failures were assertion-target mistakes, not PRD-silent rules, so they were made more faithful rather than removed.

**Fixes applied to `test_helpers/`** (both in `test_helpers/assertions.py`):
- `assert_partition_conserved` — dropped the `engagement["total_component_count"]` lookup. PRD binds `total_component_count` to the consolidated summary payload (§3.2's flat-payload sentence), not to the engagement read, whose scope counts §2.7 enumerates as the three disjoint counts plus `in_scope_component_count`. Conservation is still asserted via the sum, and the summary field itself is still covered verbatim by `test_10_endpoints.py`. Unblocked 11 tests.
- `assert_fee_breakdown` — re-pointed from the sampling plan to the engagement and reduced to the two fee fields PRD actually names (`estimated_hours`, `assessment_fee_total`). `base_amount`, `surcharge_amount`, `subtotal_amount` and `discount_amount` are never named as response fields anywhere in PRD — §2.9 calls them "intermediate money value[s] in the fee derivation" only — so asserting their presence was computed-field silence. The seven-step arithmetic and all four worked examples remain asserted through the published total. Unblocked 6 tests.

**Fixes applied to `test_suite/`:**
- `test_01_sampling_variants_and_fee.py` — 7 call sites now read the engagement the plan re-priced (§3.5 "Every plan re-prices the engagement") instead of the plan row; expected intermediates kept as comments.
- `test_05_gates_and_calendar.py:416-417` — removed the duplicate plan-level fee assertion; the same two figures are asserted on the engagement 20 lines later.
- `test_06_entities.py:241` — `sampling_stratum` on a freshly inventoried CDE host now expects `== component_type` instead of `None`. PRD §3.3 states verbatim that at creation "`sampling_stratum` mirrors `component_type` for eligible components and is null for components that fall outside the eligible population, and `in_sample` starts false"; the null-until-a-plan-exists reading applies to `in_sample`, not the stratum. (The ineligible-host case still asserts `None`, in test_01.)

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py`, `Store.touch` (plus a `_already_bumped` request-scoped helper, and registration of new rows in `stamp_new`) — a row's `version` now advances by exactly 1 per request no matter how many cascade links write to it. The segmentation verdict bumped the target zone twice (once for the status change, again when `recompute_scope_partition` rewrote that same zone's `effective_class`), so a FAIL -> re-plan -> PASS cycle reached version 7 instead of 5. PRD §2.4 ("increments by exactly 1 on every mutation", and "that engagement's `version` increments by 1 for that single request no matter how many child rows the same cascade touched") and §3.4's "both the zone's `version` and the engagement's `version` advance by 1" require the single bump. Fixing it at `touch` closes the whole class of double-bump across every cascade rather than patching one route.

**Orchestrator verification:** independently re-read all 8 `results.*.json` (timestamps 18:35, ~42.5 KB each): every round reports `total: 133, passed: 133, failed: 0, errors: 0, skipped: 0`. The clean sweep is real, not a claim without artifacts.

## Step 8: Finalize PRD — 2026-09-03T18:47:00.000Z

Done. All five edits are in `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 477 lines — `PRD_FINALIZED.md`: 477 lines — **0.0% delta** (all edits are in-sentence revisions/insertions inside existing paragraphs; no new sections, no new lines).

## Changes (one bullet each)
- **§2.4 (Resource Identity, Timestamps and Revision Counters)** — *revise* — generalized the engagement-only "one bump per request" rule to every row: a single request advances any one row's `version` by at most 1 however many cascade links rewrite it (later links only refresh `updated_at`), with the two-write segmentation verdict on a zone given as the worked case, and a row created during the request staying at `version` 1 — `implementation/db.py:128-142` (`Store.touch`), `db.py:115-126` (`stamp_new`), `db.py:145-163` (`_already_bumped`).
- **§3.2 (Commissioning an Engagement)** — *revise* — the engagement read publishes the three partition counts plus `in_scope_component_count`; `total_component_count` belongs to the consolidated `/engagements/{id}/summary` read, not the engagement read — `implementation/services/serialize.py:56-59` vs `serialize.py:88-91`.
- **§3.3 (Drawing the CDE Boundary)** — *revise* — pinned what "eligible" means for `sampling_stratum` at component creation (`scope_class`, i.e. the owning zone's current `effective_class`, is `CDE` or `CONNECTED`) and noted that later segmentation cascades move `scope_class` without rewriting the stratum — `implementation/routes/segments.py:285-297`, `services/derive.py:275-289`.
- **§3.5 (Sampling, Fee Derivation, Scope Lock)** — *insert* — one sentence after step seven: only `estimated_hours` and `assessment_fee_total` are published, and on the engagement (plus the §3.2 consolidated read); base, surcharge, subtotal, discount are unpublished intermediates and the plan payload carries no fee field — `services/derive.py:327-329`, `services/serialize.py:67-68, 95-96, 140-155`.
- **§4 endpoint table, `GET /sampling-plans/{id}`** — *revise* — dropped "and fee breakdown" from the description; the fee the plan derived is read from the engagement it re-priced — `services/serialize.py:140-155`, `routes/sampling.py:88-90`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 version semantics.** (a) Subject: how a row's `version`/`updated_at` advance when several cascade links write the same row. (b) Enumerated: `db.py` `Store.touch` / `stamp_new` / `_already_bumped` (the only writers of `version`, confirmed by grep across routes/services/middleware — no route mutates `version` directly; the only other hits are `roc_version_label` and `expected_*_version` inputs); `stamp_new(row, versioned=False)` call sites for the two unversioned types (`routes/requirements.py:208` evidence, `routes/scans.py:282` change-log); the multi-write cascade sites `derive.recompute_scope_partition` (zone `effective_class` + component `scope_class`), `derive.mark_latest_plan_stale`, `routes/segments.py` verdict path, `routes/sampling.py` supersede-then-create path. (c) Adjustment: worded the rule as "at most 1 ... later links only refresh `updated_at`" rather than "exactly 1", because `touch` refreshes `updated_at` unconditionally while suppressing the second bump; and added the created-row clause because `stamp_new` pre-registers new rows. Deliberately did not say the rule is per-cascade or per-endpoint — it is per-request, globally in `touch`, including paths Step 7 never exercised (plan supersede, worksheet accept, dispute rejection).

**Edit 2 — §3.2 engagement read fields.** (a) Subject: which scope counts the engagement read publishes vs the summary read. (b) Enumerated: `serialize.engagement` (full field list read line by line — `cde/connected/out_of_scope/in_scope_component_count`, no `total_component_count`), `serialize.engagement_summary` (has `total_component_count`), `derive.partition_counts` (computes all five, so the value exists but is only surfaced by the summary), grep for `total_component_count` across the impl -> only `derive.py:146` and `serialize.py:91`. (c) Adjustment: used "every gap and requirement count" (loose) instead of enumerating gap counters, so the sentence does not accidentally exclude `unmet_requirement_count`, `applicable_requirement_count`, `accepted_ccw_count`, `active_sampling_plan_id`, `active_plan_stale`, `quarterly_scan_compliant`, `scope_affecting_change_count` or `reassessment_required`, all of which the engagement read does carry.

**Edit 3 — §3.3 `sampling_stratum`.** (a) Subject: every impl path that writes `sampling_stratum`. (b) Enumerated via grep: `routes/segments.py:297` (creation, keyed on the freshly derived `scope_class`), `routes/sampling.py:101-105` (plan creation, keyed on the variant's eligible set), `serialize.py:134` (read-through); plus `derive.recompute_scope_partition:275-289`, confirming the FAIL/PASS cascades rewrite `scope_class` but never `sampling_stratum`. (c) Adjustment: added the explicit "a later segmentation cascade moves `scope_class` without rewriting `sampling_stratum`" clause — without it, defining the stratum in terms of the current `effective_class` would have implied continuous re-derivation, which the cascade path does not do; and kept the §3.5 selection step named as the re-derivation point so the plan path is not contradicted.

**Edit 4 — §3.5 published fee fields.** (a) Subject: where fee figures and their intermediates surface. (b) Enumerated via grep for the fee tokens: `calc.assessment_fee:181-193` (base/surcharge/subtotal/tier/discount are locals only), `derive.store_fee:327-329` (writes the two fields onto the engagement row), the three recompute call sites `routes/sampling.py:56-88`, `routes/ccws.py:170-192`, `routes/engagements.py:113-114 & 186-199`, and the two serializers that expose them (`serialize.py:67-68`, `95-96`); confirmed `serialize.sampling_plan` and `serialize.roc_report` carry no fee field. (c) Adjustment: named both surfaces ("the engagement read and ... the consolidated read of §3.2") rather than just the engagement, since the summary payload also publishes the pair; and phrased the intermediates as "appear in no payload" rather than "are not computed", since §2.9 still governs their 2-decimal precision inside the derivation.

**Edit 5 — §4 sampling-plan endpoint description.** (a) Subject: the documented content of `GET /sampling-plans/{id}`. (b) Enumerated: `routes/sampling.py:136-141` (`get_sampling_plan` -> `serialize.sampling_plan`), `routes/sampling.py:123-133` (list variant, same serializer, so the fix had to be phrased as a property of the plan payload rather than of the single read), `serialize.sampling_plan:140-155`. (c) Adjustment: pointed the reader at the engagement for the fee instead of merely deleting the phrase, so §3.5's "Every plan re-prices the engagement" stays discoverable from the table.

Note on scope: the two `test_helpers/assertions.py` fixes and the three `test_suite/` fixes all trace to the same four subjects above (engagement vs summary `total_component_count`, engagement vs plan fee fields, `sampling_stratum` at creation); the `test_05:416-417` duplicate-assertion removal was a pure fixture redundancy and produced no PRD edit of its own.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields 20 lines across 5 hunks (both files 477 lines), so the edits are real in-place revisions and the file was not truncated or left byte-identical.

## Step 9: Complete PRD — 2026-09-03T19:25:25.924Z

Run as **three sequential file-partitioned passes** over `implementation/`, so that each pass could be exhaustive over its own slice and the scan could not silently no-op (a known failure mode where PRD_COMPLETED.md comes back byte-identical to PRD_FINALIZED.md). Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited the same file in place with surgical Edit calls only.

### Pass 1 of 3 — slice: app.py, db.py, errors.py, response.py, middleware.py, routes/registry.py, routes/engagements.py, routes/segments.py

477 lines / 113,259 chars -> 479 lines / 122,326 chars (+2 lines, +9,067 chars) via 28 surgical Edit calls. **33 ambiguity-pins, 10 mismatch-revisions.**

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`; `api_request_timestamp` reads the logical clock — response.py:24-35
- §2.3 — insert — ambiguity — non-numeric `limit`/`offset` is 400; whitespace tolerated — middleware.py:218-237
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation sequence; new paragraph pinning filter semantics (exact case-sensitive text match, int filter non-integer -> 400, bool accepts true/1/yes|false/0/no with any other spelling yielding an empty page, unknown params ignored) — db.py:166-168, middleware.py:249-270
- §2.4 — insert — ambiguity — client-supplied instants/dates are echoed byte-for-byte, never re-rendered into the server's 3-digit form — middleware.py:157-184, registry.py:26
- §2.5 — insert — ambiguity — `to_iso8601` may carry `Z` or an offset, clock may move backwards, reply's sole field is `current_utc` and mirrors the input's fractional style — db.py:52-58, registry.py:169-175
- §2.9 — insert — ambiguity — money/percentage/score figures are JSON numbers, not strings — services/calc.py:82-84
- §2.10 rung 2 — insert — ambiguity — an unrecognised `X-User-Role` yields `ERR_UNAUTHORIZED`, not `ERR_UNAUTHENTICATED` — middleware.py:49-58
- §2.10 rung 3 — insert — ambiguity — strict int/bool typing, explicit `null` == absent (except re-parent detach), unknown body fields ignored, absent body == `{}`, non-object body -> 400 — middleware.py:65-154
- §2.11 — insert — ambiguity — the forest check at declaration can never refuse; `ERR_SEGMENT_CYCLE` is reachable only via re-parenting — segments.py:25-63
- §3.1 — revise — **mismatch** — assessor `status` is not a creation input (supplied value ignored); `SUSPENDED` only via amendment — registry.py:33-39
- §3.1 — insert — ambiguity — email uniqueness is exact/case-sensitive and never self-colliding — registry.py:29-31, 78-81
- §3.1 — revise — **mismatch** — vendor `approval_status` is not a creation input; name comparison exact/case-sensitive — registry.py:111-115, 151-154
- §3.2 — insert — ambiguity — creator need not be the named `lead_assessor_id`; `assessment_year` is any unbounded integer — engagements.py:66-70
- §3.2 — insert — ambiguity — commissioning never enforces the fiscal ceiling — engagements.py:112-115
- §3.2 — insert — ambiguity — intra-rung order of the four people checks (segregation -> qualification -> active -> certification; lead before reviewer), window test last — engagements.py:86-92
- §3.2 — insert — ambiguity — all five amendment fields optional, `null` is a no-op (`qa_reviewer_id` cannot be cleared); a single supplied date is compared against the stored counterpart after the engagement resolves but before `qa_reviewer_id` is looked up — engagements.py:156-172
- §3.3 — revise — **mismatch** — a zone declared beneath a live failure expansion is born `effective_class` `CDE` — segments.py:62
- §3.3 — insert — ambiguity — declaring a zone does not move the engagement's `version` — segments.py:60-63
- §3.3 — insert — ambiguity — omitting `parent_segment_id` on re-parent leaves it unchanged but still bumps `version` — segments.py:95, 125-127
- §3.3 — insert — ambiguity — withdrawal `reason` is required but not persisted — segments.py:227
- §3.3 — insert — ambiguity — `ERR_DUPLICATE_HOSTNAME` is reported before `ERR_FACILITY_TYPE_CONFLICT`; the target zone's `segmentation_status` is irrelevant at inventory — segments.py:270-283
- §3.3 — insert — ambiguity — inventorying a component does not move the engagement's `version` — segments.py:300-302
- §3.4 — revise — **mismatch** — test planning has no `SCOPING`/`FIELDWORK` status check; the frozen band answers `ERR_ENGAGEMENT_FROZEN`, never `ERR_INVALID_ENGAGEMENT_STATE`; `planned_date` is unconstrained — segments.py:141-150
- §3.4 — insert — ambiguity — the verdict `note` must be a string but is not persisted — segments.py:163
- §3.4 — revise — **mismatch** — on `PASS` a zone stays `CDE` when an ancestor is still expanded, and descendants carrying their own expansion also stay `CDE` — services/derive.py:263-289
- §3.5 — insert — ambiguity — scope lock checks the validated CDE zone before the plan; a missing or `PRELIMINARY` active plan -> `ERR_SAMPLING_PLAN_STALE`; the frozen band answers `ERR_INVALID_ENGAGEMENT_STATE` — engagements.py:236-250
- §4 intro — insert — ambiguity — optional trailing slash on every path; unroutable path -> `ERR_INVALID_REQUEST`/404, wrong method -> `ERR_INVALID_REQUEST`/405 — app.py:33, 42-51
- §4 table — revise — **mismatch** x4 — `POST /assessors` ("initial availability status"), `GET /assessors` ("lead qualification"), `GET /engagements` ("filterable by client"), `PATCH /network-segments/{id}` ("descriptive attributes or declared classification" -> re-parent only) — registry.py:33-39, 51-55; engagements.py:124-131; segments.py:91-128
- §5 intro — insert — ambiguity — `ERR_INTERNAL`/500 exists outside the catalogue table — app.py:52-56, errors.py:4

Note from pass 1: the full error-catalogue status codes in `errors.py` were cross-checked against the §5 table and every id matches; `ERR_INTERNAL` is the only impl id absent from it (now pinned).

### Pass 2 of 3 — slice: routes/sampling.py, routes/requirements.py, routes/ccws.py

479 lines / 122,326 chars -> 479 lines / 127,883 chars (+5,557 chars) via 31 surgical Edit calls. **21 ambiguity-pins, 11 mismatch-revisions.**

- §3.5 — insert — ambiguity — `justification_text` is echoed on the plan payload; `expected_engagement_version` must be a JSON integer but is unbounded — sampling.py:29-30, serialize.py:143
- §3.5 — revise — ambiguity — step three's "eligible" is the *variant* population, so `PRELIMINARY` keys `sampling_stratum` off `declared_scope_class` — sampling.py:17-21,101-104
- §3.5 — insert — ambiguity — supersession sweeps every non-`SUPERSEDED` plan and bumps its `version` by 1 — sampling.py:62-66
- §3.5 — insert — ambiguity — a draw bumps the engagement's `version` and the `version` of only those components it actually rewrote — sampling.py:86-89,107,120
- §3.6 — revise — ambiguity — `requirement_ref` shape is never validated; duplicate check is exact/case-sensitive across all requirements of the engagement — requirements.py:28,36-38
- §3.6 — insert — ambiguity — adding a requirement leaves the engagement's `version`/`updated_at` unmoved — requirements.py:55-57
- §3.6 — revise — **mismatch** — the `procedure_ref`/`evidence_type`/`component_id` triple carries no uniqueness constraint; repeats are accepted and counted — requirements.py:195-209
- §3.6 — insert — ambiguity — whitespace-only interviewee fields answer `ERR_INTERVIEWEE_REQUIRED`; in-sample rule applies to any `evidence_type`; the three rung-13 rules fire target->interviewee->in-sample — requirements.py:186-193
- §3.6 — insert — ambiguity — an evidence append rewrites the three derived positions **without** bumping the requirement's `version`/`updated_at`, and never touches the engagement — requirements.py:210
- §3.6 — insert — ambiguity — `ERR_SAMPLING_PLAN_STALE` beats `ERR_EVIDENCE_INCOMPLETE` on the same request — requirements.py:115-120
- §3.6 — revise — **mismatch** — `IN_PLACE`/`NOT_TESTED` conclusions leave `remediation_status` exactly as it stood (can stay `GAP_OPEN`), not "at `NONE`" — requirements.py:122-126
- §3.6 — insert — ambiguity — `NONE -> GAP_OPEN` is conditional on standing at `NONE`; an already-`GAP_OPEN` row stays there and still mints a further item — requirements.py:124-126
- §3.6 — insert — ambiguity — reopen `reason` is required, non-empty, and not persisted — requirements.py:137
- §3.7 — revise — **mismatch** — "six narrative sections" -> five narratives plus two control parameters (matches the five-field list at submission) — ccws.py:13-14
- §3.7 — insert — ambiguity — narratives are required keys but may be empty/whitespace at draft; emptiness is only policed at submission — ccws.py:44,122-125
- §3.7 — insert — ambiguity — drafting bumps the parent requirement's `version` by 1 and leaves the engagement untouched — ccws.py:80
- §3.7 — insert — ambiguity — superseding a worksheet bumps its `version` and preserves its note/decision/rigor figures — ccws.py:61-64
- §3.7 — revise — **mismatch** — the `NOT_IN_PLACE` requirement precondition is enforced on `ACCEPT` only; also pinned monitoring-before-rigor order and that the stored `rigor_score` is used, never recomputed — ccws.py:152-153,164-167
- §3.7 — insert — ambiguity — `GAP_OPEN -> GAP_ACCEPTED_CCW` is conditional; a `GAP_REMEDIATED` requirement keeps `GAP_REMEDIATED` — ccws.py:182-183
- §3.7 — revise — ambiguity — `due_date` is required, strict `YYYY-MM-DD`, stored byte-for-byte, no ordering constraint — ccws.py:229,240
- §3.7 — revise — **mismatch** — retest `PASS`: no `evidence_completeness` check exists; each of the two requirement moves is independently from-state-gated; when other items stay open the requirement is untouched and only item+engagement versions advance — ccws.py:272-284
- §2.6 — insert — ambiguity — "deciding a compensating control worksheet" added to the operations unaffected by `FROZEN` — ccws.py:138-155 (no `guard_frozen`)
- §3.6 — insert — ambiguity — `conclusion_rationale` required and non-empty — requirements.py:106
- §3.7 — insert — ambiguity — `reviewer_note` required and non-empty on both decision arms — ccws.py:143
- §3.7 — insert — ambiguity — `owner_reference` required and non-empty — ccws.py:228
- §3.7 — insert — ambiguity — retest `note` must be a string when supplied but is not persisted — ccws.py:251
- §4 — revise — **mismatch** — requirement-assessment list filters: dropped nonexistent "tester", added `applicability` — requirements.py:66-72
- §4 — revise — **mismatch** — start-testing does not "assign the testing assessor"; no payload, no tester field — requirements.py:86-98
- §4 — revise — **mismatch** — evidence-items list filters: added engagement and sufficiency — requirements.py:219-226
- §4 — revise — **mismatch** — ccws list filter is `thin_control_capped`, not "rigor" — ccws.py:89-94
- §4 — revise — **mismatch** — remediation-items list filters: dropped nonexistent "owner", added source-scan-finding and severity — ccws.py:206-213
- §4 — revise — **mismatch** — assignment is available from `OPEN` *and* `RETEST_FAILED`, not just "open" — ccws.py:236-237

### Pass 3 of 3 — slice: routes/rocs.py, routes/scans.py, services/calc.py, services/derive.py, services/serialize.py

479 lines / 127,883 chars -> 479 lines / 133,871 chars (+5,988 chars). **15 ambiguity-pins, 6 mismatch-revisions.**

- §2.7 — revise — mismatch — "cascade propagation is depth-first" replaced with the per-zone upward-chain re-derivation the impl actually uses, noting no traversal order is observable (`services/derive.py:275-289`; `descendant_closure` is dead code)
- §3.2 — insert — ambiguity — engagement read payload enumerated exactly as the serializer emits it, and `unmet_requirement_count` defined as requirements at `NOT_IN_PLACE`/`NOT_TESTED` (`serialize.py:43-77`, `derive.py:190`)
- §3.7 — insert — ambiguity — exact `gap_description` template and the three per-source trigger phrases (`derive.py:360-374`)
- §3.8 — insert — ambiguity — `roc_version_label` required and non-empty (`rocs.py:37`)
- §3.8 — insert — ambiguity — the three business preconditions fire in written order (testing-incomplete beats already-exists); `NOT_APPLICABLE` rows never count as untested (`rocs.py:46-53`)
- §3.8 — revise — mismatch — creation writes `applicable_requirement_count` too, and the engagement's percentages are read-derived, not mirrored onto its row (`rocs.py:22-30,68`)
- §3.8 — insert — ambiguity — zero denominator publishes 0.00, not null (`calc.py:163-166`)
- §3.8 — revise — mismatch — "five writes recompute the projection" -> only creation and QA approval freeze it onto the report (`rocs.py:68,135`)
- §3.8 — insert — ambiguity — `qa_decision_note` required and non-empty on both arms (`rocs.py:119`)
- §3.8 — revise — mismatch — `APPROVE` refreshes the whole projection, not just the two percentages (`rocs.py:135`)
- §3.8 — insert — ambiguity — `revision_note` required, non-empty, never persisted (`rocs.py:146`)
- §3.8 — insert — ambiguity — `attestation_signature_name` non-empty; the three attest conditions tested in written order (cert beats no-passing-scan) (`rocs.py:168,177-182`)
- §3.8 — revise — mismatch — `submission_reference` non-empty; the 365-day due date is set only while `reassessment_required` is false (`rocs.py:202,218-220`)
- §3.9 — insert — ambiguity — `quarter_label` non-empty and exact-case unique; `window_start` echoed verbatim and `window_end` rendered in the input's fractional style (`scans.py:28,57-58`, `db.fmt_like`)
- §3.9 — insert — ambiguity — scheduling rewrites no engagement field, so its `version` does not move (`scans.py:53-71`)
- §3.9 — insert — ambiguity — `severity_class` reads the supplied score before the 1-dp rounding (3.96 -> `cvss_score` 4.0 but `LOW`); publishing a finding refreshes the cycle ledger without bumping the cycle's `version` (`scans.py:138-139,147`)
- §3.9 — revise — mismatch — dispute conditions reordered to the impl's ladder order (finding state, cycle state, then severity), plus no caller/engagement relationship is policed and `dispute_rationale` is non-empty (`scans.py:177,184-189`)
- §3.9 — insert — ambiguity — `decision_note` non-empty; `attestation_of_scan_compliance` set true on the `DISPUTE_OPEN -> PASSING` flip (`scans.py:207,229`)
- §3.9 — insert — ambiguity — flag cleared to false on the `-> FAILING` flip, and a rejection leaving another dispute open moves nothing (`scans.py:235-238`)
- §3.9 — insert — ambiguity — change-log recording polices no caller relationship; `affects_scope` is a required boolean (`scans.py:259,263`)
- §3.9 — insert — ambiguity — the due-date pull-forward fires only on the exactly-third triggering entry and leaves the engagement's `version`/`updated_at` unmoved (`scans.py:285-290`)

### Aggregate

- `PRD_FINALIZED.md` 477 lines / 113,259 chars -> `PRD_COMPLETED.md` **479 lines / 133,871 chars (+2 lines, +20,612 chars)**.
- **69 ambiguity-pins, 27 mismatch-revisions** across the three passes (96 changes), every one a surgical in-paragraph Edit; no new sections.

**Orchestrator verification:** independently confirmed `PRD_COMPLETED.md` is 479 lines / 133,871 chars, is **not** byte-identical to `PRD_FINALIZED.md` (`diff` reports 71 hunks — so the scan genuinely ran), carries all five `## ` sections (lines 3/11/169/329/405), and ends on the final `ERR_ASSESSMENT_BUDGET_EXCEEDED` table row rather than mid-sentence. Also confirmed via `find -newer` that no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` changed after Step 7's green sweep, so the recorded 8x 133/133 result still describes the shipped artifacts.

## Pipeline complete — 2026-09-03T19:25:25.924Z

All nine steps finished. Final state: 133 tests, 133/133 passing in all 8 parallel sweep rounds; `workspace/PRD_COMPLETED.md` written.
