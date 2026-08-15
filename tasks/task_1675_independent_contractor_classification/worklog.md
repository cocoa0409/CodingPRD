# Worklog — task_1675_independent_contractor_classification

## Step 1: Create Task Directory — 2026-08-14T06:41:00.000Z

Task directory `tasks/task_1675_independent_contractor_classification/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed.

## Step 2: Generate Scaffold — 2026-08-14T07:29:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1675_independent_contractor_classification/`):
- `SCAFFOLD.yaml` (1197 lines) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~1040 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (~1330 lines) — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **14** (Jurisdiction, Contractor, Engagement, IntakeQuestionnaire, ClassificationDetermination, ExceptionGrant, ContractAgreement, ContractAmendment, MonitoringReview, RiskAudit, RemediationAction, TaxForm1099Filing, AgencyInquiry, ConversionCase)
- State machines: **11** (Engagement cyclic w/ review loop + suspend/reinstate cycle; Contractor parallel dimensions verification×standing; ContractAgreement; ContractAmendment; ExceptionGrant; MonitoringReview; RiskAudit w/ auto-compound REMEDIATION; RemediationAction; TaxForm1099Filing correction/resubmission cycles; AgencyInquiry escalation round cycle; ConversionCase diamond)
- Endpoints: **60** (deliberately above the Expert band ceiling of 32, per the harder-than-expert request; includes `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Errors: **32**; Validations: **32** (10 priority tiers); Roles: **9** (all opaque, segregation-of-duties model); OCC concurrency rules: **2**
- Difficulty instances: **19** (≥2 per rule; combinatorial_formula carries 3 — one each in modes (a) scope-creep nested min/max, (b) conversion lookback per-quarter-round-then-sum, (c) agency exposure pinned evaluation order)
- Corner instances: **45** (44 active + 1 `excluded_because` stub), spanning all 9 claim-guide sections

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(568 calls scanned across 19 + 44 instances; 60 endpoints, 14 entities)

**Notable design decisions:**
- **Multi-jurisdiction classification** as the Rule-1 dual-variant anchor: identical questionnaire answers yield EMPLOYEE_RISK under ABC_TEST (one failed prong) but CONTRACTOR under COMMON_LAW_WEIGHTED (score 0.25 < 0.60); ECONOMIC_REALITY adds a third divergent variant. Second dual-variant pair lives on RiskAudit (provisional forward-looking 12.0 LOW vs final fieldwork-replay 58.6 HIGH).
- **All numeric asserts pre-computed in Python** and pinned as literals — including a deliberately chosen lookback fixture ([1000300, 1000400, 1005200, 1003400] cents) where the pinned per-quarter rounding (5610815) diverges from sum-then-round (5610814) by exactly one cent.
- **Two true-race OCC rules only** (determination-create on Engagement.version, amendment-create on ContractAgreement.version); all other write conflicts were re-classified as state preconditions per §1.2.1's filter.
- **Two transitive cascades**: suspend (depth 4: Engagement→Contract→Amendment→Exception→standing, asymmetric on reinstate) and conversion-acceptance (depth 3: ConversionCase→Engagement→Contractor standing→sibling engagements auto-rejected).
- **Layered approvals** with tier-dependent quorum (1/2/3), strict role sequencing, X-User-ID segregation of duties, and a HIGH-tier exception-grant gate positioned so safety-vs-referential and state-vs-fiscal priority duels are both testable.
- Boundary precision pins: 1099 threshold inclusive at exactly 60000 cents, penalty tier edge at 30 vs 31 days late, risk level inclusive at exactly 50.0, review findings empty-set (CLEARED) vs one-finding (FINDINGS_FILED).
- One real reachability gap was found and fixed during §1.9 replay: questionnaire resubmission from CLASSIFIED needed a declared self-loop, added to the Engagement machine and the endpoint description.

## Step 3: Copy Shared Files — 2026-08-14T07:30:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1675_independent_contractor_classification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T07:52:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1675_independent_contractor_classification/workspace/PRD.md` — 338 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs, pain-point + design-commitment angle)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 9 roles with individual opaque-identity prose), 2.2 API Response Structure (fixed verbatim block, byte-identical), 2.3 Pagination (`limit` 10/1–100, `offset` 0, `created_at` ascending, 4 `meta` fields), 2.4 Common Resource Properties (incl. the `common_fields: false` exception for ClassificationDetermination — only `id` + `created_at`), 2.5 Logical Clock & Lazy Expiry (startup default 2026-08-01T00:00:00Z, no wall-clock fallback; lazy `EXPIRED` for ExceptionGrant and ContractAgreement), 2.6 OCC (both concurrency rules with exact endpoint, `expected_engagement_version`/`expected_contract_version`, `ERR_STALE_VERSION`/`ERR_STALE_CONTRACT_VERSION`, 412), 2.7 Nested Existence Ordering (left-to-right 404 triage), 2.8 Money/Scores/Rounding, 2.9 Validation Priority (10-rung ladder with worked ordering examples), 2.10 Cascading Consistency & Terminal Lockdown
- §3 Business Logic — 9 subsections grouped by lifecycle concern (jurisdictions/test theory, contractor onboarding, intake questionnaire loop, determinations & review pipeline, approval quorum & exceptions, contracts/amendments/suspension cascade, monitoring/scope-creep/audits, 1099 filings, inquiries & conversions)
- §4 Endpoint table — 60 rows, 4 columns only
- §5 Error catalogue — 32 rows, 2 columns only

**Hard contract results:**
- Contract 1 (field coverage): 120 required identifiers (entity fields + endpoint inputs + query params + nested payload keys), 0 missing — PASS
- Contract 2 (rule coverage): verified manually — 10-rung validation priority expressed with explicit ordering examples; both OCC rules named with endpoint/field/error/status and no race framing; all cascade links (suspend 1–4, conversion 1–3, supersession), compound transitions, asymmetric reinstatement, all calculation formulas (3-variant classification test, provisional/final risk scores with event caps, scope creep with suspended floor, conversion lookback with pinned per-quarter rounding incl. the 5610815-vs-5610814 fixture, 1099 thresholds, late-penalty tiers, exposure pinned order incl. the 5000000/2-quarter worked pin), all `applies_to` scopes enumerated — PASS
- Contract 3 (§3 path purity): 674 backticked tokens scanned in §3, 0 paths / 0 bare methods / 0 combos — PASS
- Supplementary scans: 32/32 error IDs and 9/9 role names in backticked prose; no pseudocode operators (`==`, `>=`, `min(`, …) and no fuzzy words ("approximately", "conservatively", …) in the prose.

**Notable generation decisions:**
- *Scattering:* the three classification-test variant formulas live in §3.1 (jurisdiction regime context) while determination OCC/supersession/risk-tier mechanics live in §3.4; exception-grant rules split across §3.5 (capacity/revocation) and §3.6 (execution gate, amendment `exception_grant_id`); standing gates introduced in §3.2 and re-applied in §3.5/§3.6. Contract amendment parameters (`new_rate_cents`, `new_end_date`) sit in §3.6 while the scope-creep consequences land in §3.7.
- *Verbatim block:* §2.2 copied byte-identical from `section-2.2-response-structure.md` (with `req_RANDOMALPHANUM123456`, `"data": { }` untouched).
- *Worked pins included:* the two pinned-arithmetic fixtures (conversion lookback 5610815 vs 5610814; exposure 6050000) come from `SCAFFOLD.yaml`'s own calculation blocks (not from the withheld difficulty files) and were included because Contract 2's reconstruction test requires disambiguating the pinned evaluation order.
- *Ambiguity handled faithfully:* the scaffold's "within the audit window" phrase in suspend-cascade link 4 was rendered via the ExceptionGrant revoke rule's defined semantics (`GOOD_STANDING → WATCH` recompute) rather than inventing a window definition; resubmission semantics rendered as "`filed_at` stamps first submit; `days_late`/`penalty_cents` recomputed against the clock's new position" exactly as scaffolded.

## Step 6: Generate Implementation — 2026-08-14T08:12:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1675_independent_contractor_classification/workspace/implementation/`):

- `start.sh` — executable; guarded `pip install` (no-op when flask is importable); `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry, blueprint registration, ApiError/404/405/400/500 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (dicts keyed by id); logical clock initialized to exactly `2026-08-01T00:00:00Z`, never wall-clock; ISO-8601 parse/format helpers (3-fractional-digit UTC timestamps)
- `errors.py` — ApiError class + all 32 error-id constants from the scaffold catalog
- `response.py` — exact scaffold envelope (`meta.api_request_id` `req_*`, `meta.api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` inside `meta`; defaults 10/1/100/0)
- `middleware.py` — `X-User-Role`/`X-User-ID` auth, 9 declared roles, 401/403 split
- `services/core.py` — all 8 calculations (3-variant classification test, provisional/final risk score with 3-occurrence event caps, scope-creep index with supervision multiplier and SUSPENDED floor 70, pinned per-quarter conversion lookback, 1099 reportable/threshold logic, tiered late-filing penalty, pinned-order agency exposure, lifetime reconciliation) plus cascade helpers (lazy grant/contract expiry, standing downgrade/restore, HIGH-tier exception gate)
- `routes/` — 10 blueprints: jurisdictions (+`/_clock/set_current_utc`), contractors, engagements (questionnaire upsert, OCC-guarded determinations, review loop, quorum approvals with role-order + segregation-of-duties, activate/suspend/reinstate/terminate), exceptions, contracts+amendments, reviews, audits+remediation-actions, filings, inquiries, conversions

**Endpoint count: 42** (41 `/api/...` routes + 1 `/_clock/set_current_utc`), covering every row of the scaffold §1.5 endpoint table.

**Notable implementation decisions:**

- **In-memory only** — single module-level `Store`; no disk/SQLite/redis. Verified fresh boot returns empty lists and the clock resets to `2026-08-01T00:00:00Z`. No seeding anywhere.
- **Verified both PRD pinned fixtures end-to-end against the live server**: conversion lookback `[1000300,1000400,1005200,1003400]` → `w2_equivalent_total_cents=5610815` (pinned per-quarter rounding), and agency exposure base 5000000 / 2 quarters → `6050000`.
- **Validation priority ladder** implemented per PRD §2.9: auth → role → shape → existence (left-to-right with the three distinct 404 ids) → state (incl. both 412 OCC checks) → business safety gates → business constraints → temporal → referential → fiscal capacity. Confirmed observable precedence (e.g., stale-version beats questionnaire-incomplete; not-approval-pending beats order/SoD/exception checks).
- **Cascades implemented with per-resource version/timestamp bumps**: 4-link suspend cascade (contract→amendments→exception grants→contractor standing, with asymmetric reinstate), 3-link conversion-acceptance cascade (engagement→contractor standing→other non-terminal engagements REJECTED), correction supersession, compound amendment approve→apply and audit finalize→REMEDIATION, cross-entity FIELDWORK audit creation on inquiry escalation.
- **Lazy expiry** for ExceptionGrant (`clock > expires_at`) and EXECUTED ContractAgreement (`clock date > end_date`), evaluated on every read/precondition use — verified via clock jump.
- **Parallel Contractor dimensions** tracked independently; standing restore requires the closed action's audit to reach 0 open actions AND no other audit of the contractor to have open actions.
- Determinations are append-only (no `updated_at`/`version`, listed newest-first) per PRD §2.4; `original_rate_cents` is captured at first EXECUTED transition for the scope-creep rate-variance term.

## Step 5: Generate Unit Tests — 2026-08-14T08:40:00.000Z

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1675_independent_contractor_classification/test_helpers/`
- `types.py` — 9 role/status enums + 14 entity TypedDicts; `ClassificationDetermination` correctly carries only `id` + `created_at` (append-only, PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (46 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 32 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py` (canonical 8-factor answer sets + per-call unique EINs), `constants.py`, `test_users.py` (all roles opaque; distinct approver IDs hr-001/legal-001/board-001 for quorum/SoD), `fixtures.py` (`setup_engagement_at_state` driving DRAFT→…→TERMINATED incl. HIGH-tier exception handling, plus audit/filing/inquiry/conversion composites)
- `__init__.py` barrel

**`test_suite/` (9 files, 81 tests)** — `.../test_suite/`
| file | tests |
|---|---|
| test_01_engagement_intake_and_access_control.py | 11 |
| test_02_classification_and_determinations.py | 7 |
| test_03_review_loop_approvals_and_exceptions.py | 12 |
| test_04_contracts_amendments_and_activation.py | 9 |
| test_05_cascades_and_agency_inquiries.py | 12 |
| test_06_monitoring_reviews.py | 5 |
| test_07_risk_audits_remediation_and_standing.py | 11 |
| test_08_filings_and_lifetime_reconciliation.py | 14 |

**Coverage audit (machine-checked)**
- 81 tests = 81 unique `Design:` tags; pytest collects cleanly; every quoted citation greps verbatim against PRD.md (0 misses); no skip/xfail markers.
- Queue A: 18/19 instances × ≥2 tests = 36 difficulty tests. Queue B: 44/44 non-stub instances × ≥1 test = 45 corner tests.

**Instances skipped**
1. **Difficulty/combinatorial_formula/cf_scope_creep_multi_input_nonlinear** — asserts `scope_creep_index == 64` read *after* a clock advance with no intervening recompute trigger. PRD §3.7 enumerates recompute triggers (amendment applied, review closed, engagement mutation) and §2.5 confines lazy clock evaluation to ExceptionGrant and ContractAgreement, so a faithful PRD-only implementation storing the value at trigger time returns 54. Not uniquely derivable → gap left as a gap.
2. **Corner/calculations/calc_1099_input_set_filtering** — `excluded_because` stub; cross-reference to `bpc_reportable_threshold_exact_60000` resolves; not translated per spec.

**Notable decisions**
- **Same-rung ambiguity (error-precedence silence pattern):** `val_determination_required_for_submit_review` and `sm_activate_from_classified_rejected` each face two simultaneously-failing rung-5 errors (§2.9: "Entries within a rung share priority"), so they assert via `validate_error_is_one_of` rather than a single hard-coded error ID.
- **Underivable literals relaxed:** contractor `version == 1` (PRD never pins the initial version → presence/type only); `filed_at` asserted by instant prefix `2026-08-01T00:00:00` rather than exact string (serialization not pinned); `days_late`/`penalty_cents` asserted exactly.
- **Fixed during self-review:** duplicate jurisdiction code hazard in the late-penalty test (two `setup_contractor_with_filing` calls now use US-CA and US-NV); removed a dead setup in the HIGH-tier exception test.

## Step 7: Run Tests and Iterate — 2026-08-14T08:58:00.000Z

All 8 parallel rounds pass 81/81. Clean sweep achieved.

**Summary**

- **Iterations run:** 2 (first sweep: 9 deterministic failures in all 8 rounds; second sweep after fixes: 81/81 × 8 rounds, zero failures, zero flakes).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability; no PRD-silent or scaffold-only assertions were found.

- **Fixes applied to test artifacts:**
  - `test_suite/test_03_review_loop_approvals_and_exceptions.py` — added missing `setup_high_tier_engagement` import (NameError in `test_approver_already_acted_rejected`; the helper is exported from `test_helpers` but was absent from the import list).
  - `test_suite/test_04_contracts_amendments_and_activation.py` — (a) `_setup_expired_grant_high_engagement` referenced the bare `api` fixture name outside fixture scope (NameError in both `TestExecutionGatePriority` tests); switched to the `api_client` singleton, which is exactly what the `api` fixture returns. (b) `TestContractPeriodOverlap._approved_with_contract` built the pre-existing EXECUTED contract with `end_date=2026-06-01`, which lies before the logical clock's startup instant (2026-08-01, PRD §2.5); a PRD-faithful server lazy-expires it to `EXPIRED` on the next read, removing it from the overlap peer set (`DRAFT`/`EXECUTED`/`SUSPENDED`, PRD §3.6) — so the overlapping second contract was correctly accepted. Fixture dates moved to end 2026-12-01 (still overlap-rejecting the 2026-05-01→2026-09-01 probe), and the adjacency test's probe shifted to 2026-12-01→2027-04-01 to preserve the half-open adjacency assertion.
  - `test_suite/test_08_filings_and_lifetime_reconciliation.py` — `test_reportable_amount_at_federal_boundary` and `test_reportable_amount_one_cent_below_boundary` used `setup_contractor_with_filing(verify=False)`, which pre-creates a DRAFT `ORIGINAL` filing for tax_year 2026; the tests then created their own `ORIGINAL` 2026 filing for the same contractor, and the server correctly rejected it with `ERR_DUPLICATE_FILING` (PRD §3.8 per-recipient/year uniqueness). Replaced the fixture with direct `create_jurisdiction` + `create_contractor` calls (the pre-made filing was never part of the asserted behavior).

- **Fixes applied to implementation:**
  - `workspace/implementation/routes/engagements.py` (`list_determinations`) — sorted by `created_at` descending only; since `created_at` is stamped from the frozen logical clock, same-test determinations tie and Python's stable sort kept oldest first, violating PRD §3.4's "ordered newest first". Now sorts ascending (stable) and reverses, so ties resolve to most-recently-created first.
  - `workspace/implementation/routes/exceptions.py` (`grant_exception`) — added the PRD §2.9 rung-5 terminal lockdown (`REJECTED`/`TERMINATED`/`CONVERTED` → `ERR_INVALID_STATE`) before the rung-10 fiscal capacity check; previously a grant attempt on a terminal engagement with `max_active_exceptions=0` surfaced `ERR_EXCEPTION_CAPACITY_REACHED`, violating the validation priority ladder.

## Step 8: Finalize PRD — 2026-08-14T09:06:00.000Z

Done. `workspace/PRD_FINALIZED.md` written — a single inline revision, everything else verbatim.

**Line counts / %-delta:** PRD.md 337 lines → PRD_FINALIZED.md 337 lines, 0% line-count delta (the PRD uses one-paragraph-per-line formatting; the change appends one sentence inside §3.4's existing paragraph at line 161).

**Changes (one total):**
- §3.4 — revise — appended the tie-break pin: "A determination's `created_at` is stamped from the logical clock, which does not advance unless explicitly set, so successive determinations can share the same `created_at`; ties on `created_at` are ordered with the most recently created determination first." — impl: `workspace/implementation/routes/engagements.py:264-265` (stable ascending sort then `reverse()`), with `created_at` sourcing at `engagements.py:246` and `workspace/implementation/db.py:36-39`.

**Step 7 diff items that produced no edit (with reason):**
- test_03 missing `setup_high_tier_engagement` import — pure test bug (NameError), no behavioral content.
- test_04(a) bare `api` fixture NameError — pure test bug.
- test_04(b) pre-existing contract ending 2026-06-01 (before the 2026-08-01 clock startup) lazy-expiring out of the overlap peer set — PRD already pins this: §2.5 mandates lazy contract expiry "on any read or write of the contract" and §3.6 restricts overlap peers to `DRAFT`/`EXECUTED`/`SUSPENDED`; the impl (`contracts.py:49-60`) lazy-expires each peer inside the overlap scan exactly as the PRD reads. Fixture bug only.
- test_08 duplicate-filing fixture — PRD §3.8 already pins per-recipient/year `ORIGINAL` uniqueness ("neither `VOID` nor `SUPERSEDED`", so DRAFT counts). Fixture bug only.
- `grant_exception` terminal-lockdown-before-capacity — an impl-side fix toward the PRD, not a silence: §2.9 rung 5 explicitly lists "terminal lockdown of `REJECTED`, `TERMINATED`, or `CONVERTED` engagements", rung 10 is fiscal capacity, and the ladder preamble states an earlier-rung failure "never surfaces a later rung's error". Current impl (`exceptions.py:32-35`) now matches; PRD prose kept verbatim.

**Per-edit pre-edit search log (for the single edit):**
- (a) Subject: ordering semantics of the determination-history list, specifically tie-breaking among determinations sharing an identical `created_at`.
- (b) Impl paths enumerated and read/grepped: `routes/engagements.py:256-267` `list_determinations` (the only determination-listing endpoint — confirmed by repo-wide grep for `determination` across `implementation/`); `routes/engagements.py:211-253` `create_determination` (stamps `created_at` via `now_iso()`); `db.py:36-39` `now_iso` (reads only `store.clock`); `db.py:26` + `routes/jurisdictions.py:77-85` (clock set at startup and mutated only by `/_clock/set_current_utc` — never auto-advances); `services/core.py:44-53` `touch`/`stamp_new` (all timestamps logical-clock-derived); `services/core.py:150-155, 246-247, 269-270` (pointwise `current_determination_id` reads — no ordering); grep of every other list endpoint (`exceptions.py:71`, `filings.py:115`, `contractors.py:59`, `jurisdictions.py:72`, `audits.py:69,172`, `inquiries.py:70,83`, `reviews.py:63`, `engagements.py:126`, `contracts.py:86,111,223`, `conversions.py:65`) — all sort ascending by `created_at` only, untouched by this edit since §3.4 already declares determinations the exception to §2.3. Also checked PRD §4's routing-table row ("List all determinations of an engagement, newest first") — left as-is; the summary phrase stays consistent with the refined §3.4 wording.
- (c) Wording adjustment: scoped the clock claim to determinations ("A determination's `created_at` is stamped from the logical clock") rather than asserting anything universal about all resources' `created_at`, and phrased the tie rule as "ties on `created_at` … most recently created first" — not "reverse creation order" — so the sentence stays true for non-tied records (where the impl orders strictly by `created_at` descending, regardless of insertion sequence) and silent for all other list endpoints.

## Step 9: Complete PRD — 2026-08-14T09:28:00.000Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Source:** `workspace/PRD_FINALIZED.md` (337 lines / 65,160 bytes) → `PRD_COMPLETED.md` (337 lines / 68,724 bytes; +3,564 chars). All changes are inline inserts/revisions within existing paragraphs; no new sections; line count unchanged.

**Counts:** 28 ambiguity-pins, 4 mismatch-revisions.

### Mismatch revisions
- §2.9 rung 5 — revise — mismatch — removed `ERR_CORRECTION_REQUIRES_ACCEPTED` from the state-validity rung (impl checks it after the verification gate) — implementation/routes/filings.py:138-146
- §2.9 rung 6 — revise — mismatch — removed the high-tier exception requirement (`ERR_EXCEPTION_REQUIRED`) from business safety gates (impl evaluates it after approval-order/segregation checks) — implementation/routes/engagements.py:322-334
- §2.9 rung 9 — revise — mismatch — added `ERR_EXCEPTION_REQUIRED` and `ERR_CORRECTION_REQUIRES_ACCEPTED` to referential soundness, matching impl evaluation points — implementation/routes/engagements.py:333-334, contracts.py:183-199, filings.py:142-146
- §3.5 — revise — mismatch — `ClassificationAnalyst` may reject from `APPROVAL_PENDING` as well as `UNDER_REVIEW` (impl's role check is endpoint-level); also pins rejection `reason` as not persisted — implementation/routes/engagements.py:346-354

### Ambiguity pins
- §2.3 — insert — pagination out-of-range/unparseable `limit`/`offset` are clamped to [1,100]/[0,∞), never rejected — implementation/response.py:48-67
- §2.4 — insert — `version` starts at 1; `updated_at` equals `created_at` at creation — implementation/services/core.py:44-53
- §2.5 — insert — clock set accepts any parseable instant, no monotonicity constraint — implementation/routes/jurisdictions.py:77-86
- §2.5 — insert — grant lazy expiry flips status only (no `updated_at`/`version` change); contract lazy expiry is a full mutation (touches) — implementation/services/core.py:56-70
- §2.7 — insert — unmatched paths → `ERR_RESOURCE_NOT_FOUND` 404; unsupported method → `ERR_INVALID_REQUEST` 405; unparseable/non-object JSON body treated as empty object — implementation/app.py:34-48
- §3.1 — insert — duplicate jurisdiction `code` → `ERR_INVALID_REQUEST` 400 — implementation/routes/jurisdictions.py:46-48
- §3.1 — insert — `employee_score_threshold` is validated/defaulted/stored for all `test_type`s, effective only under `COMMON_LAW_WEIGHTED` — implementation/routes/jurisdictions.py:21,31-36
- §3.2 — insert — duplicate `ein` → `ERR_INVALID_REQUEST` 400 — implementation/routes/contractors.py:31-33
- §3.2 — insert — verify no-op outcomes (`VERIFIED` on `VERIFIED`, `FAILED` on `VERIFICATION_FAILED`) accepted with version increment; `FAILED` on `VERIFIED` → `ERR_INVALID_STATE` 409 — implementation/routes/contractors.py:79-89
- §3.3 — insert — `required_approval_count` also stays null until a determination exists — implementation/routes/engagements.py:101-102
- §3.4 — insert — request-info `reason` is neither required nor persisted — implementation/routes/engagements.py:291-299
- §3.6 — insert — contract carries `original_rate_cents`, null until first execution — implementation/routes/contracts.py:72,137-139
- §3.6 — insert — missing `exception_grant_id` on HIGH tier → `ERR_EXCEPTION_REQUIRED` 422; unresolvable grant → `ERR_RESOURCE_NOT_FOUND` 404; grant validation runs after the stale-version check — implementation/routes/contracts.py:177-199
- §3.6 — insert — amendment proposals accepted against contracts in any status; `EXECUTED` required only at adjudication — implementation/routes/contracts.py:172-213
- §3.7 — insert — review begins with empty `findings`, `findings_count` 0, null `outcome` — implementation/routes/reviews.py:43-55
- §3.7 — insert — unresolvable remediation action id at review close → `ERR_REVIEW_NOT_CLOSABLE` (not 404) — implementation/routes/reviews.py:96-100
- §3.7 — insert — scope creep recompute triggers extended: contract execution, suspension, reinstatement — implementation/routes/contracts.py:141-142, engagements.py:415,433
- §3.7 — insert — formula uses the engagement's earliest-created contract; rate variance is zero also when no contract has reached `EXECUTED` yet — implementation/services/core.py:173-187
- §3.7 — insert — full-calendar-month counting is day-of-month anchored with negative spans floored at zero — implementation/services/core.py:226-231
- §3.7 — insert — provisional score counts grants by stored `ACTIVE` status and does not trigger lazy expiry — implementation/services/core.py:249-252,273-279
- §3.7 — insert — new audit also carries null `findings_summary` — implementation/routes/audits.py:44-55
- §3.8 — insert — line-item `amount_cents` accepts any integer, including negative — implementation/routes/filings.py:52-54
- §3.9 — insert — inquiry registration not gated on engagement status; inquiry records denormalized `contractor_id` — implementation/routes/inquiries.py:45-51
- §3.9 — insert — `response_summary` required but not persisted — implementation/routes/inquiries.py:92-106
- §3.9 — insert — conversion `service_fee_cents` must be an integer ≥ 0 — implementation/routes/conversions.py:36-38
- §3.9 — insert — new conversion case has null `offer_salary_cents` — implementation/routes/conversions.py:46-54
- §3.9 — insert — `offer_salary_cents` must be an integer ≥ 0 — implementation/routes/conversions.py:74-76
- §5 — insert — `ERR_INVALID_REQUEST` additionally returned with HTTP 405 for unsupported methods — implementation/app.py:38-40

Notable cross-checks that required no change: all endpoint role grants, the three classification test formulas, approval quorum/segregation mechanics, suspension/conversion/supersession cascades, 1099 reporting/penalty math, exposure-estimate pinned order, conversion lookback pinned rounding, and determination newest-first tie-breaking all matched the implementation exactly.
