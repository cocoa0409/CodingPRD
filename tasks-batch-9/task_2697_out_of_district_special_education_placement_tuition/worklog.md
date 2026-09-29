# Worklog — task_2697_out_of_district_special_education_placement_tuition

## Step 1: Create task directory — 2026-09-04T08:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2697_out_of_district_special_education_placement_tuition` and its `workspace/` subdirectory. Index 2697 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T10:01:00.000Z

All three scaffold artifacts for task_2697 are complete and lint-clean.

## Files

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | **3219** | §1.0–§1.7 only — verified to contain **neither** `scaffold_difficulty_design` nor `scaffold_corner_design` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **3029** | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **5155** | single key `scaffold_corner_design` |

## SCAFFOLD.yaml (`difficulty_level: beyond_expert`)
15 entities · 11 state machines · 2 §1.2.1 concurrency rules · 10 calculations · 39 validations on a 13-rung total priority ladder · **70 endpoints** · 51 error codes · 7 roles (2 entity-backed, `role_model: segregation_of_duties` with two SOD pairs). Archetype: ledger reconciliation over multi-party negotiation; `entity_topology: flat`, `state_machine_shape: cyclic`, `consistency_model: immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

## §1.8 — 9 rules / 24 instances
`dual_variant_calc` 3 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2.

## §1.9 — all 9 sections / 89 instances (61 full recipes + 28 `excluded_because` stubs)
entities 10 · state_machines 16 · calculations 14 · validations 18 · endpoints 7 · errors 10 · rbac 5 · cross_cutting_complexity_layers 8 · consistency_model 1. Every `claim_type` is a verbatim row from `references/claim-extraction-guide.md`; the only guide rows deliberately absent are inapplicable ones (Immutability / Parent Relationships — all entities are `common_fields: true`, `parent: null`; Bulk action — no bulk endpoints declared).

## Verification
- `scaffold_lint.py`: **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (70 endpoints, 15 entities, 24 §1.8 + 61 §1.9 instances, **1231 calls** scanned).
- All 28 stub `difficulty_instance` citations resolve to real §1.8 names (lint does not check this — done manually).
- `name` unique across the §1.8 ∪ §1.9 union (113 names, 0 collisions); no stub carries a `test_recipe`; every full recipe has all four `test_recipe` keys.
- **Error coverage: 51/51 codes appear in at least one `assert` string** (audited programmatically, not just mentioned in `grounds`).
- 57/70 endpoints have a structured `setup_api_calls`/`trigger` call; the remaining 13 are the collection-level GETs, which appear as follow-up-read assertions in prose.
- Every entity, calculation and role name is referenced by the two design files.

Bugs found and fixed while writing §1.9: three grounds/assert references pointed at fields and a calculation that do not exist in SCAFFOLD.yaml (`Student.ytd_placement_cost_cents`, `calculations.invoice_variance_ratio`, `ERR_INVOICE_VARIANCE_EXCEEDED`). Corrected to the real `Student.high_cost_flag` / `projected_state_recovery_cents`, `calculations.invoice_verified_amount.constants` and `TuitionInvoice.verification_status`; the `consistency_model` instance now asserts that CASCADE-B LINK 3/LINK 4 correctly do *not* fire on a 654400 payment (below the 4000000 high-cost trigger).

## Step 3: Copy shared files — 2026-09-04T10:01:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T10:22:00.000Z

The PRD is complete.

**Output:** `workspace/PRD.md` — **571 lines**, last heading `## 5. Error Code Catalogue`, file ends on the final table row `| ERR_HIGH_COST_CAP_EXHAUSTED | 402 |` (a real section boundary, not mid-sentence).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Audit Columns and the Logical Clock · 2.5 Whole-Cent Money and Rounding Discipline · 2.6 The District Fiscal Ledger · 2.7 Stale-View Guards · 2.8 Cascade Propagation · 2.9 Collection Addressing and Reverse Lookup · 2.10 The Order in Which Requests Are Refused
- §3 Business Logic & Workflows — 3.1 Standing Reference Data · 3.2 Decision Record and Revision Cycle · 3.3 Contracting a Placement · 3.4 Related Services and Transportation · 3.5 Attendance Reporting and Invoice Verification · 3.6 Payment Approval, Disbursement and State Recovery · 3.7 Parental Unilateral Reimbursement · 3.8 Progress Monitoring and Return-Readiness Gate · 3.9 Closing a Placement: Termination vs Return
- §4 API Endpoint Definitions (4-column table, 70 rows)
- §5 Error Code Catalogue (2-column table, 51 rows)

**Coverage confirmed** (machine-verified against the scaffold, code fences excluded from token extraction): 15 entities · 70 endpoints (table row count = 70 exactly) · 51 error codes (all appear in backticks in prose, all in §5) · 10 calculations (all named formulas rendered in precise prose) · 39 validations · 40 state-machine transitions · 2 concurrency rules · 7 roles · 65 enum values.

```
Field coverage check:
- entities[].fields: 180 required, 180 present, 0 missing   (176 declared + 4 common: id, created_at, updated_at, version)
- endpoints[].request_body: 98 required, 98 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_placement_version / expected_school_version + ERR_STALE_PLACEMENT_VERSION / ERR_STALE_SCHOOL_VERSION all named, 412), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 37 write endpoints + 2 computed reads + clock endpoint checked, all expressed, 0 missing
- entities[].fields[] structured content: 180 checked, 180 reconstructible from prose, 0 missing
- sibling-branch symmetry: 13 groups checked (attendance ACCEPT/DISPUTE; invoice VERIFIED/DISPUTED; award FULL/PARTIAL/DENIED; report ACCEPT/REJECT; terminate/return-to-district; assignment ACTIVE/WAITLISTED resolution; assignment ACTIVE/WAITLISTED release; decision return/approve; both cost-projection variants; both readiness variants; both award_basis variants; both invoice bases; HIGH_COST_FUND/MEDICAID), 13 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1258
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold inconsistencies resolved (worth flagging downstream)**
1. `FundingClaim.eligible_base_cents` / `tier_rate` field descriptions say "0 for MEDICAID", but `calculations.funding_claim_reimbursable` computes `eligible_base_cents = round_half_up(hours × 9000)` and `tier_rate = FMAP_PCT` for MEDICAID. I followed the calculation block (the endpoint side-effect explicitly says the calculation writes those fields).
2. `ReturnTransitionPlan` activate: endpoint `roles: [TeamChair]` vs SM9 `actor: PlacementCoordinator`. I followed the endpoint role list (authoritative for §4/authorization).
3. `Placement.end_date` entity constraint `>= start_date` vs validation p10 `> start_date` — followed the validation.
4. `ServiceAddendum` (placement_id, service_type) uniqueness and the `billing_period_start/end` must-equal-record rule have no declared error_id; mapped to `ERR_DUPLICATE_RESOURCE` and `ERR_INVALID_REQUEST` respectively. Activation preconditions without codes mapped to `ERR_INVALID_STATE_TRANSITION`.
5. Scaffold validation prose says "X-Role"; used the mandated `X-User-Role`.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling task directory was read.

**Orchestrator truncation check:** `tail -25` confirms PRD.md terminates on the final row of the §5 error table (`ERR_HIGH_COST_CAP_EXHAUSTED | 402`), a real section boundary. All 5 top-level sections and 20 subsections present. 132370 bytes. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T11:15:00.000Z

Implementation complete.

## Location
`workspace/implementation/`

## Modules (18 files, 4023 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` (only if flask missing) + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 85 | app factory, 7 blueprint registrations under `/ood-placements`, clock blueprint at root, `ApiError`/404/405/400/500 envelope handlers |
| `store.py` | 193 | in-memory `Store` (15 dicts), logical clock pinned to `2026-08-01T00:00:00Z`, `new_row`, once-per-request `touch()`/`reset_touch()`, deterministic `ordered()` |
| `errors.py` | 92 | all 51 error codes → HTTP status, `ApiError`, `fail()` |
| `response.py` | 70 | `meta`/`response_type`/`data` envelope, pagination meta, error body |
| `middleware.py` | 132 | 7 roles, header auth, `endpoint()` decorator (rungs 1–2), entity-backed scope for SchoolBillingAgent/ParentGuardian, `check_scope`/`scope_filter` |
| `validation.py` | 307 | rung-4 typed field readers (incl. whole-cent ints, 0.25-hour multiples, dates/instants), query-param readers, pagination bounds |
| `calc.py` | 466 | every pinned constant + all 10 calculations (encumbrances, invoice pricing, report score, readiness, reimbursement award, high-cost tiering, Medicaid, cost projection, waitlist selector) with `Decimal`/`ROUND_HALF_UP` |
| `cascades.py` | 283 | ledger primitives, Cascade A (`close_placement`, 10 links), Cascade B (`approve_payment_cascade`, 5 links), waitlist promotion, activation-grace lapse sweep |
| `common.py` | 141 | enum vocabularies, 15 `*_or_404` lookups, list plumbing |
| `routes_reference.py` | 337 | clock, fiscal accounts, students, private schools, rate schedules (OCC on school version), transport routes |
| `routes_decisions.py` | 230 | placement decisions + revision/approval cycle with LRE-completeness gate and SoD |
| `routes_placements.py` | 354 | proposal, execute-contract, activate, terminate, return-to-district, cost-projection |
| `routes_services.py` | 264 | service addenda + authorize, transportation assignments + release/promotion |
| `routes_billing.py` | 485 | attendance records (verify/amend) and tuition invoices (create with OCC, verify, resubmit, approve-payment) |
| `routes_claims.py` | 318 | reimbursement claims (adjudicate/remand) and funding claims (high-cost + Medicaid, submit-to-state) |
| `routes_progress.py` | 255 | quarterly progress reports + return transition plans, `/readiness` read, 4-rung activate gate |

## Endpoints
Exactly **70** wired, verified by dumping `app.url_map` — matches the PRD §4 table 1:1 (69 under `/ood-placements` + `POST /_clock/set_current_utc`).

## Smoke test (`PORT=39697`)
Booted cleanly via `bash start.sh`. I ran a 60-call end-to-end driver covering the full lifecycle: account → student → school → rate schedule → decision (submit/approve) → placement → execute-contract → route → transport assignment → addendum authorize → clock advance → activate → attendance verify → invoice create/verify (DISPUTED at 26.86% variance → resubmit → VERIFIED) → approve-payment (SoD rejection first, then a second FiscalOfficer) → 3 progress reports → readiness (90.6, met) → plan activate → Medicaid funding claim + submit-to-state → high-cost threshold rejection → reimbursement claim adjudicate/remand → return-to-district → pagination bounds → parent scope. **0 failures**; every asserted status code matched, and the ledger identity `authorized = available + encumbered + disbursed` held exactly (900,000,000 = 898,929,628 + 250,000 + 820,372) after the closure cascade.

Server killed by its recorded PID only; port 39697 confirmed free. `__pycache__` removed, no stray files in `workspace/`. Storage is dicts only — no persistence, no seeding at import.

## Step 5: Generate unit tests — 2026-09-04T12:09:00.000Z

All work is complete and verified.

## Files written

`test_helpers/` (9 files, 2760 lines)

| file | lines |
|---|---|
| `__init__.py` | 40 |
| `api_client.py` | 534 |
| `api_errors.py` | 207 |
| `assertions.py` | 176 |
| `constants.py` | 166 |
| `factories.py` | 399 |
| `fixtures.py` | 838 |
| `test_users.py` | 133 |
| `types.py` | 267 |

`test_suite/` (13 files, 6136 lines)

| file | lines | tests (A + B) |
|---|---|---|
| `conftest.py` | 78 | — |
| `test_01_placement_decision_review.py` | 320 | 6 (2 + 4) |
| `test_02_placement_contract_and_activation.py` | 595 | 14 (6 + 8) |
| `test_03_transport_seats_and_windows.py` | 498 | 8 (4 + 4) |
| `test_04_attendance_verification.py` | 357 | 6 (2 + 4) |
| `test_05_invoice_pricing.py` | 613 | 12 (10 + 2) |
| `test_06_invoice_payment_cascade.py` | 406 | 7 (4 + 3) |
| `test_07_funding_claims.py` | 516 | 7 (2 + 5) |
| `test_08_reimbursement_claims.py` | 434 | 7 (4 + 3) |
| `test_09_progress_reports_and_return_readiness.py` | 560 | 12 (8 + 4) |
| `test_10_placement_closure_forks.py` | 453 | 6 (6 + 0) |
| `test_11_access_control.py` | 486 | 7 (0 + 7) |
| `test_12_resource_identity_and_listing.py` | 820 | 17 (0 + 17) |

Nothing was written under `workspace/`, and `workspace/implementation/` was never read or touched.

## Coverage

- **Queue A (difficulty):** 24 live instances, 0 stubs, exactly 2 tests each → **48 tests**. `MISSING = 0`.
- **Queue B (corner):** 61 live instances (28 `excluded_because` stubs emit nothing), exactly 1 test each → **61 tests**. `MISSING = 0`.
- **Total 109 test functions / 110 pytest node ids** (one test is parametrized with two cases: `test_08 … TestEquitableFindingsGate::test_the_equitable_basis_without_sufficient_findings_is_refused[omitted|twenty_one_characters]`).

## Verification passes (all green)

1. Every test has exactly one `Design:` line, it is the last docstring line, and every tag resolves to a real **non-stub** instance — 0 unknown tags, 0 tags pointing at stubs, 0 dual tags.
2. Every test has exactly one `PRD: "…"` line and all 109 quotes are literal substrings of `workspace/PRD.md`.
3. No file in `test_helpers/` or `test_suite/` mentions "scaffold".
4. `py_compile` clean and `pyflakes` clean (exit 0) on all 22 modules; `pytest --collect-only` collects 110 tests with no errors.

## Instances skipped

None beyond the design indices' own stubs: 0 difficulty stubs and 28 corner instances carrying `excluded_because`, which by contract emit nothing. Every live instance in both queues produced a test — no instance was dropped for failing the PRD-first filter.

## PRD-vs-design deviations (asserted the PRD, not the design note)

1. `Corner/calculations/cost_projection_run_rate_diverges_from_contracted_encumbrance` — design says `periods_paid == 1` under `CONTRACTED_ENCUMBRANCE`; PRD §3.6 reports 0 → asserted 0.
2. Difficulty A#2 — design says `readiness_score_at_activation == 0` on a DRAFT plan; PRD §3.8 says null → asserted `is None`.
3. `Corner/endpoints/progress_report_reject_decision_takes_the_rejected_branch` — design keeps `report_score == 80.00` on REJECT; PRD §3.8 zeroes it → asserted 0.
4. Difficulty A#9 — design asserts `verified_amount_cents == 767182`, but its own single-addendum 7.5-hour setup derives **712363** (19 × 32000 = 608000 tuition; 7.5 × 11000 × 1.075 = 88688 service; gross 696688 < 700000 so no volume credit; fee 15675) → asserted 712363.
5. Both `Corner/rbac` segregation-of-duties instances say `ERR_SEGREGATION_OF_DUTIES` returns 403; PRD §2.1 and the §4 error table say **409** → asserted 409 via the PRD-declared status map.
6. The decision-SoD instance asserts `approved_by_user_id` on a `PlacementDecision`; the PRD names that column `reviewed_by_user_id` (`approved_by_user_id` exists only on `TuitionInvoice`) → asserted `reviewed_by_user_id`.

**Orchestrator placement check:** `test_helpers/` (9 files) and `test_suite/` (13 files) both confirmed at the task root; `find workspace -name test_helpers -o -name test_suite` returned nothing. `__pycache__` dirs removed.

## Step 7: Iterate tests + fixes — 2026-09-04T13:00:00.000Z

Two iterations of the 8-round parallel stability sweep (`--isolation per-test-server`, `setsid`-detached, no early exit). Every round in both iterations ran to completion; the failure set was identical in all 8 rounds of iteration 1, so nothing was load-induced or flaky.

| iteration | per-round result |
|---|---|
| 1 | 99/110 in all 8 rounds (11 deterministic failures) |
| 2 | **110/110 in all 8 rounds** |

### Deletions
None. Every failing test cited a rule that PRD.md states verbatim and uniquely determines.

### Fixes in `test_helpers/`
- `assertions.py` — added `assert_instant_equals()`. PRD §2.4 pins the three-fractional-digit rendering only for `created_at`, `updated_at` and `meta.api_request_timestamp`; the transition stamps (`activated_at`, `promoted_at`, `submitted_at`, …) are specified only as "the logical clock's current instant", and the clock itself is quoted as `2026-08-01T00:00:00Z`. Byte-equality against the string the test fed the clock was therefore not uniquely derivable, so the covered claim (the stamp *is* that instant) is kept and the uncovered claim (its exact rendering) dropped.
- `fixtures.py` — added `make_active_placement_with_transport()` and taught `build_active_day_placement()` to use it whenever `placement_overrides["transportation_required"]` is true. §3.3 gates activation on "at least one transportation assignment on this placement must already be `ACTIVE`" while §3.4 only permits a seat request on a `CONTRACTED` or `ACTIVE` placement, so the seat has to be booked between contract execution and activation. The old fixture activated first and then assigned, which made every transportation world fail setup with `ERR_INVALID_STATE_TRANSITION`.

### Fixes in `test_suite/`
- `test_02` / `test_03` / `test_07` / `test_10` — five instant comparisons switched to `assert_instant_equals`.
- `test_06 …TestPaymentGuards::test_billing_transport_days_without_an_active_assignment_is_refused` — the world now releases the seat the (now correct) fixture booked, which is the only PRD-reachable shape for "an ACTIVE placement that requires transportation and has no `ACTIVE` assignment"; the stale `transport_status == "PENDING"` precondition became `"RELEASED"`.
- `test_07` — `CAP_TRIM_CENTS` 19014 → 39014. Pure constant arithmetic bug: 2519507 − 2480493 = 39014. The server's own figures (2519507, then 5000000 − 2519507 = 2480493) were already asserted correctly and passed.
- `test_10 …TestTerminationPromotesTheWaitlist` — `_waitlisted_pair_world` now leaves the second placement `CONTRACTED` instead of trying to activate it. A waitlisted rider has no `ACTIVE` assignment, so a `transportation_required` placement behind it can never legally activate; `CONTRACTED` is exactly what §3.4's promotion candidate filter admits ("whose parent placement is currently `CONTRACTED` or `ACTIVE`"). The `placement_b["status"]` assertion follows.
- `test_12 …TestFundingClaimComputedFields` — `claim["claim_source"]` → `claim["source"]`; §3.6 names the column `source`.
- `test_12 …TestBodyForeignKeys` — the five-way loop passed `student_id` both positionally and via `**{field: …}`, a `TypeError` before any request left the client. It now builds the payload and overwrites the one key.
- `test_12 …TestStaleSchoolVersionOnRatePublication` — `FY2028_RATES` used `effective_start` / `effective_end`; the declared fields are `effective_from` / `effective_to`, so rung 4's no-unknown-fields rule returned `ERR_INVALID_REQUEST` before the OCC guard was ever reached.

### Fixes in `implementation/`
- `cascades.py`, `close_placement()` Link 8 — the abandoned transition plan's reserve release now also adds to the placement's `released_encumbrance_cents`. §2.6: "A placement's `released_encumbrance_cents` accumulates **every cent it has ever pushed back into `available_cents`** — through termination, return to district, activation-grace expiry, addendum termination or transportation release." Link 8's own enumeration is silent on the counter, but the §2.6 invariant governs, and the return-to-district sibling (which does *not* release the reserve) already agreed with the test at 6552000.
**Orchestrator sweep verification (independent of the subagent's report):** `results.{1..8}.json` all present (~37 KB each, same 12:26 mtime) and each parses to `passed=110, total=110, failed=0`. Step 7's clean-sweep claim is confirmed against the artifacts, not taken on report. Step 7 applied 1 `implementation/` fix (plus 2 `test_helpers/` and 7 `test_suite/` fixes), so the Step 8 skip condition does NOT apply — Step 8 runs.

## Step 8: Finalize PRD — 2026-09-04T13:35:00.000Z

`workspace/PRD_FINALIZED.md` is written.

## Size
- PRD.md: 571 lines / 132,370 bytes → PRD_FINALIZED.md: 571 lines / 132,915 bytes.
- Line delta: 0 lines (**0.00%**). Byte delta: +545 bytes (**+0.41%**). Two in-place sentence revisions, no new sections.

## Changes
- **§2.4 (Resource Identity, Audit Columns and the Logical Clock)** — *revise* — after the sentence listing the transition stamps, added that every ISO 8601 UTC instant the system renders carries exactly three fractional digits (audit columns, `meta.api_request_timestamp` and every transition stamp alike), with the worked example that a clock set to `2026-09-01T08:00:00Z` yields `2026-09-01T08:00:00.000Z` rather than the supplied string echoed verbatim — `implementation/store.py:57-70` (`iso()` / `now_iso()`).
- **§3.9 Cascade A, Link 8** — *revise* — the abandoned plan's reserve release now also states that the placement's `released_encumbrance_cents` rises by that reserve, cross-referenced to the §2.6 invariant — `implementation/cascades.py:180-193`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: the textual rendering of every server-produced ISO 8601 UTC instant, not just `activated_at`/`promoted_at`/`submitted_at` from the Step 7 site.
- (b) Enumerated impl paths: `store.py:57 iso()` (the single formatter, `%02d…%03dZ`); `store.py:69 now_iso()`; `store.py:123 new_row()` (`created_at`/`updated_at`); `store.py:159 touch()` (`updated_at`); `response.py:22 _meta()` (`api_request_timestamp`, all of `ok`/`created`/`ok_list`/`error`); `routes_decisions.py:173,221` (`submitted_at`, `decided_at`); `routes_placements.py:260,306` (`contract_executed_at`, `activated_at`); `cascades.py:79,137,283` (`promoted_at`, `terminated_at` on both close modes and on the lapse sweep); `routes_claims.py:315` (funding-claim `submitted_at`); `routes_reference.py:58` (the clock endpoint's `current_utc` echo). Also grepped `get_instant` across the whole impl to prove no client-supplied instant is ever persisted or echoed verbatim (only `routes_reference.py:55`, non-persisted) — so a universal claim about rendering has no counterexample anywhere in the codebase.
- (c) Adjustment: I initially planned to pin only the six transition stamps §2.4 names, but the enumeration showed the formatter is universal (the clock echo included), so I widened the sentence to "every ISO 8601 UTC instant this system renders" and deliberately did **not** enumerate the clock-echo field by name, to avoid asserting a response shape §4 never specifies. Restricted the claim to *instants* so it cannot be misread as touching date-only fields (`start_date`, `notice_date`, `iep_effective_date`, …).

**Edit 2 — §3.9 Link 8 `released_encumbrance_cents`**
- (a) Subject: every place a placement pushes cents back into `available_cents` and therefore accumulates `released_encumbrance_cents`.
- (b) Enumerated impl paths: `cascades.py:115-123 release_contract_commitment()` (Link 1 and the lapse sweep at `:285` — both already pinned by PRD §3.9 Link 1 and §3.3); `cascades.py:150-159` addendum release loop, used for both the `TERMINATED` and `TRANSFERRED` terminal states (pinned by Link 3 / Divergence one); `cascades.py:95-108 unwind_active_assignment()`, reached from Cascade A Links 4-5 *and* from the standalone `routes_services.py:242` release endpoint (pinned by §3.4 and Link 5); `cascades.py:181-196` Link 8 itself — TERMINATE branch releases and now accumulates, RETURN branch sets `COMPLETED` and moves nothing; `calc.recompute_placement_encumbrance` callers. Also checked `reverse_direct()` (remand) — it touches only a fiscal account, never a placement counter, so it is outside the subject.
- (c) Adjustment: worded the addition as a consequence of §2.6 ("because those cents have just been pushed back into `available_cents`") rather than as a fresh standalone rule, so it cannot be read as contradicting **Divergence two** on the return-to-district path, where the reserve is retained and no cents move back — the RETURN branch legitimately accumulates nothing there.

**Items deliberately *not* patched** (traced to the Step 7 diff, found to be already uniquely determined by PRD.md):
- `fixtures.py` seat-before-activation reordering — §3.3's activation gate and §3.4's `CONTRACTED`-or-`ACTIVE` precondition both state it verbatim; confirmed against `routes_services.py:172-177` and the activation handler. Pure fixture bug.
- test_06 `transport_status` `PENDING`→`RELEASED` — §3.4's "becomes `RELEASED` only when no other `ACTIVE` assignment remains" determines it (`routes_services.py:244-249`).
- test_07 `CAP_TRIM_CENTS` 19014→39014 — arithmetic slip in a test constant; §3.6's cap-trim rule is unambiguous.
- test_10 waitlisted-pair world left `CONTRACTED` — §3.4's promotion candidate filter names `CONTRACTED` or `ACTIVE` verbatim.
- test_12 `claim_source`→`source`, the `**kwargs` `TypeError`, and `effective_start/_end`→`effective_from/_to` — all three are test-side name/shape bugs against field names §3.6, §2.9 and §3.1 already declare.

## Step 9: Complete PRD — 2026-09-04T14:20:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (a single agent scanning 4023 lines of implementation against a 571-line PRD reliably under-scans; pass 1 owned the `cp`, passes 2 and 3 were told explicitly not to re-create the file). Total: **57 ambiguity-pins, 5 mismatch-revisions across 62 edits.**

### Pass 1 — app.py, store.py, errors.py, response.py, middleware.py, validation.py, common.py, routes_reference.py, routes_decisions.py
19 ambiguity-pins, 1 mismatch-revision.
- **§2.1** — insert — ambiguity — entity-backed scope narrowing bites only on rows that resolve to an owner of the acting role's kind; enumerated exactly which collections each of `SchoolBillingAgent`/`ParentGuardian` resolves and which are unrestricted (incl. reimbursement claims being unrestricted for agents) — `middleware.py:86-120`
- **§2.1** — insert — ambiguity — `X-User-ID` is never existence-checked for entity-backed roles; a bogus school/student id still authenticates and is merely out of scope — `middleware.py:33-43`
- **§2.2** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters — `response.py:10,18`
- **§2.3** — insert — ambiguity — non-integer or out-of-range `limit`/negative `offset` → `ERR_INVALID_REQUEST`; no upper bound on `offset` — `validation.py:246-269`
- **§2.3** — insert — ambiguity — `created_at` ties (routine under a logical clock) break by insertion order — `store.py:171-173`
- **§2.3** — insert — ambiguity — `total_count` is computed *after* entity-backed scope narrowing — `common.py:128-134`
- **§2.4** — insert — ambiguity — a row's `version` advances exactly once per cascade however many links write it, with the clock sweep's per-placement epochs as the stated exception — `store.py:136-160`, `cascades.py:280`
- **§2.4** — insert — ambiguity — the clock endpoint answers 200 with `data` = `{current_utc}`; the clock may move backwards — `routes_reference.py:52-58`
- **§2.9** — insert — ambiguity — string/status/enum filters are exact-equality and *not* vocabulary-checked (empty page, no 400/404); only `fiscal_year` and `high_cost_flag` are shape-checked; undeclared query params ignored — `validation.py:272-307`, `common.py:137-141`
- **§2.10 rung 4** — insert — ambiguity — absent/empty body reads as `{}`; non-object body is 400; required strings must be non-blank after trimming except free narrative text — `validation.py:21-37,77-78`
- **§2.10 rung 12** — revise — **mismatch** — "the three uniqueness rules" was wrong: impl has eight `ERR_DUPLICATE_RESOURCE` sites; rewritten as the four unique reference codes plus the live-duplicate bars named in §3 — `routes_reference.py:78,122,184,321`
- **§3.1 (rates)** — insert — ambiguity — publication validates the effectivity dates only as calendar dates: no `effective_to ≥ effective_from` rule, no fiscal-year containment, no school-approval check — `routes_reference.py:252-259`
- **§3.1 (rates)** — insert — ambiguity — supersession is exhaustive over all `STATE_APPROVED` incumbents; the school's `version` moves only when the pointer changes or an incumbent was superseded, so a `DRAFT` publication preserves a held `expected_school_version` — `routes_reference.py:216-288`
- **§3.2** — insert — ambiguity — continuum entries accept only `setting`/`rejected_reason` with string-or-null values; content is unconstrained at creation (`setting` is free text, not the LRE vocabulary) — `routes_decisions.py:36-47,91-117`
- **§3.2** — insert — ambiguity — an empty-subset revision is accepted and still bumps `version`; the three fields are non-nullable and omission never clears; `revision_round`/notes/stamps untouched — `routes_decisions.py:120-142`
- **§3.2** — insert — ambiguity — the sibling-in-`TEAM_REVIEW` guard carries `ERR_INVALID_STATE_TRANSITION` and is evaluated *after* the LRE gate; submit accepts no body fields — `routes_decisions.py:152-171`
- **§3.2** — insert — ambiguity — `reviewer_notes` is mandatory on return-for-revision but may be an empty string — `routes_decisions.py:181-182`
- **§3.2** — insert — ambiguity — the `OOD_ACTIVE` guard is `ERR_INVALID_STATE_TRANSITION` evaluated after segregation of duties; an omitted `reviewer_notes` preserves prior notes; `placement_status` is set to `DECISION_APPROVED` unconditionally — `routes_decisions.py:202-230`
- **§4 preamble** — insert — ambiguity — trailing slash insignificant; unrouted path → `ERR_NOT_FOUND` (404) and undeclared method → `ERR_METHOD_NOT_ALLOWED` (405), both decided before authentication and outside the ladder — `app.py:36,47-57`
- **§5 intro** — insert — ambiguity — those two envelope-level codes are deliberately absent from the catalogue table — `app.py:47-57`

Cross-checked and left untouched: impl's `ERR_*` catalogue is an exact 51-code, same-status match to §5; the impl's 32 GET handlers match §2.1's "thirty-two read operations".

### Pass 2 — calc.py, cascades.py, routes_placements.py, routes_services.py
17 ambiguity-pins, 2 mismatch-revisions.
- §3.3 proposal — insert — ambiguity — `DAY`-with-nights refusal is `ERR_INVALID_REQUEST` but evaluated *after* body references resolve; pinned the six-identifier resolution order (`student_id` → `school_id` → `decision_id` → `rate_schedule_id` → `fiscal_account_id` → `prior_placement_id`) — `routes_placements.py:138-148`
- §3.3 execute-contract — revise — **mismatch** — PRD said the transition "re-checks the decision's status"/school standing, but proposal never tests either; both now stated as first tested here and refused with plain `ERR_INVALID_STATE_TRANSITION`, not `ERR_SCHOOL_NOT_APPROVED` — `routes_placements.py:229-237`
- §3.4 addendum proposal — insert — ambiguity — proposal is state-agnostic; the parent placement's `status` is not consulted until authorisation — `routes_services.py:76`
- §3.4 addendum authorisation — insert — ambiguity — a fiscal-authority refusal rolls the just-copied `hourly_rate_cents` back to 0 and persists nothing — `routes_services.py:119-122`
- §3.4 assignment request — insert — ambiguity — non-increasing pickup window is `ERR_INVALID_REQUEST` *before* `placement_id`/`route_id` resolve (opposite of the DAY-nights case); wrong placement state or `transportation_required` false is `ERR_INVALID_STATE_TRANSITION` — `routes_services.py:165-177`
- §3.4 promotion selector — revise — **mismatch** — PRD said "the first candidate wins"; impl skips candidates whose buffered window collides and takes the earliest clear one, promoting nothing when all collide — `calc.py:408-423`
- §3.4 promotion effects — revise — ambiguity — money lands on the *promoted* placement's own fiscal account (not the released seat's), and promotion runs with no `available_cents` test, so it can drive that account negative — `cascades.py:70-92`
- §3.5 service lines — insert — ambiguity — lines whose addendum has since gone `TERMINATED`/`TRANSFERRED` still price at the frozen rate; processing order cannot change the total — `calc.py:148-162`
- §3.5 transport route selector — revise — ambiguity — third tie-break by insertion order makes the ranking total — `calc.py:144`
- §3.5 waterfall — revise — ambiguity — `tuition_line_cents` and `gross_billable_cents` (not just credit/fee) follow the requested basis; the other three lines are basis-independent — `calc.py:205-213`
- §3.5 variance — insert — ambiguity — `verified_amount_cents` of 0 short-circuits the division: 0 when submitted is 0, exactly 1.0000 otherwise — `calc.py:200-203`
- §3.6 Cascade B Link 3 — insert — ambiguity — the link never refuses; an exhausted per-student ceiling still yields an `ELIGIBLE` claim at `reimbursable_amount_cents` 0 — `cascades.py:235-258`
- §3.6 cost projection — insert — ambiguity — `variant` *is* vocabulary-checked (`ERR_INVALID_REQUEST`), unlike §2.9 filters; absent/empty takes the default — `routes_placements.py:107`
- §3.8 report score — insert — ambiguity — goal-attainment percentage is never pre-rounded; the composite rounds exactly once — `calc.py:224-231`
- §3.8 readiness — insert — ambiguity — zero accepted reports aggregate to exactly 0.00 over an empty contributing set — `calc.py:251-252`
- §3.9 termination — insert — ambiguity — `termination_reason` required but may be an empty string — `routes_placements.py:323-324`
- §3.9 Link 1 — insert — ambiguity — the account is touched unconditionally, so a zero release still advances its `version` (contrast: zero-amount addendum releases do not) — `cascades.py:115-123`
- §3.9 Link 7 — revise — ambiguity — the promoted placement's own account is charged, unguarded and unrefusable — `cascades.py:84-91`
- §3.9 return — insert — ambiguity — `return_reason` blank-permitted; `receiving_lre_setting` from the five-value LRE vocabulary — `routes_placements.py:339-341`

Verified as already correctly pinned and left untouched: `report_scores` sliced to the two contributing rows under `trailing_two_quarter` (`routes_progress.py:195`); accepted-report ordering needs no extra tie-break because per-quarter uniqueness makes `(fiscal_year, quarter)` total. `calc.sorted_children` and `store.day_span` are dead code with no PRD footprint.

### Pass 3 — routes_billing.py, routes_claims.py, routes_progress.py
21 ambiguity-pins, 2 mismatch-revisions.
- §3.5 — revise — **mismatch** — the "three period rules" paragraph attributed the per-count 0-to-28 bounds, `residential_nights > 28` and `days_attended > days_enrolled` to `ERR_BILLING_PERIOD_SHAPE`; impl reserves that code for the 28-day span and `days_enrolled + days_absent_unexcused > 28` only, refusing the count relations and field bounds as rung-4 `ERR_INVALID_REQUEST` before `placement_id` resolves — `routes_billing.py:104-148,183`
- §3.5 — insert — ambiguity — the DAY/`residential_nights`-zero rule is `ERR_INVALID_REQUEST`, evaluated only after the placement and every named addendum resolve — `routes_billing.py:188`
- §3.5 — insert — ambiguity — service-line entry shape: both keys mandatory, no third key, non-blank id, hours ≥ 0 and an exact 0.25 multiple, all `ERR_INVALID_REQUEST`; array echoed back verbatim unnormalised — `routes_billing.py:59-83,204`
- §3.5 — insert — ambiguity — no placement-status gate at filing — `routes_billing.py:185-194`
- §3.5 — insert — ambiguity — `dispute_reason` is validated as free text (blank allowed) then discarded, on both branches — `routes_billing.py:218`
- §3.5 — insert — ambiguity — the `delivered_hours_ytd` accrual on ACCEPT is unconditional (addendum status not retested) and uncapped — `routes_billing.py:233-240`
- §3.5 — insert — ambiguity — on amend, omitted `residential_nights`/`service_delivery_lines` retain current values; the cycle is not amendable; the record is excluded from its own overlap scan — `routes_billing.py:258-261,281`
- §3.5 — insert — ambiguity — neither the record's nor the placement's status is gated at invoice creation — `routes_billing.py:334-357`
- §3.5 — insert — ambiguity — placement status not consulted at verification — `routes_billing.py:396-415`
- §3.5 — insert — ambiguity — omitted `transport_days_billed` on resubmit retains the invoice's figure — `routes_billing.py:431-433`
- §3.5 — insert — ambiguity — resubmit clears only four fields; the lines, gross, credit, fee and both variant amounts are deliberately left as the prior run computed them, `settled_amount_cents` stays 0 — `routes_billing.py:446-454`
- §3.6 — insert — ambiguity — within rung 11, the segregation-of-duties comparison precedes the attendance re-check — `routes_billing.py:467-474`
- §3.6 — revise — **mismatch** — `ERR_HIGH_COST_CAP_EXHAUSTED` fires on any zero reimbursable, so a placement sitting exactly on the 4 000 000 trigger clears the threshold gate then is refused as cap-exhausted despite nothing being exhausted — `routes_claims.py:265-269`
- §3.6 — insert — ambiguity — a hand-filed claim never raises `high_cost_flag` (only Cascade B Link 4 does), and a zero-value `MEDICAID` claim is still created `ELIGIBLE` — `routes_claims.py:271,288-290`
- §3.6 — insert — ambiguity — `state_claim_reference` is required but free-text (blank permitted); the worth-nothing refusal is `ERR_INVALID_STATE_TRANSITION` evaluated before the consent re-check; `source` plays no part — `routes_claims.py:298-313`
- §3.7 — insert — ambiguity — the two cross-field date relations are rung-4 `ERR_INVALID_REQUEST`, settled before the three body-reference lookups — `routes_claims.py:96-106`
- §3.7 — insert — ambiguity — `superseding_placement_id` is existence-checked only; its status and student are unconstrained — `routes_claims.py:105-106`
- §3.7 — insert — ambiguity — within rung 12 the equitable-findings gate answers before the concurrent-placement bar — `routes_claims.py:147-164`
- §3.7 — insert — ambiguity — `remand_reason` is required but free text (blank permitted) and persisted nowhere — `routes_claims.py:185`
- §3.8 — insert — ambiguity — the `ERR_DUPLICATE_PROGRESS_PERIOD` refusal is rung-10 (after placement resolution and scope); the two goal relations are rung-4 `ERR_INVALID_REQUEST` beforehand; no placement-status gate at filing — `routes_progress.py:82-99`
- §3.8 — insert — ambiguity — `receiving_program` required but free-text; drafting accepts a past `target_return_date` and any placement status — `routes_progress.py:166-186`
- §3.8 — insert — ambiguity — `transition_services` is a required array-of-strings, so omission/wrong type is rung-4 `ERR_INVALID_REQUEST`; `[]` or all-blank reaches the rung-11 completeness check — `routes_progress.py:211,228-230`
- §3.8 — insert — ambiguity — the readiness `variant` is vocabulary-checked (`ERR_INVALID_REQUEST` on an unknown value, default on absent/empty), and `accepted_report_count` counts every `ACCEPTED` report under both variants, not just the trailing window's two — `routes_progress.py:192-203`

### Orchestrator verification of the final artifact
- `PRD.md` 571 lines / 132,370 B → `PRD_FINALIZED.md` 571 lines / 132,915 B → `PRD_COMPLETED.md` **575 lines / 152,830 B** (+19,915 B, **+15.0%** over PRD_FINALIZED).
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` **differs** — the scan demonstrably ran (the byte-identical failure mode did not occur). 116 changed lines across the three passes.
- `diff` of the heading lists is **empty**: all 27 headings intact, no sections added, none lost — every edit was an in-paragraph insert or revision.
- File terminates on the final row of the §5 error table (`ERR_HIGH_COST_CAP_EXHAUSTED | 402`), a real section boundary — not truncated.
- Step 9 touched no implementation code, so the Step 7 sweep artifacts `results.{1..8}.json` (all 110/110) remain the valid final evidence.

**Pipeline complete.**
