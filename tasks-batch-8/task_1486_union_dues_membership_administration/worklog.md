# Worklog — task_1486_union_dues_membership_administration

## Step 1: Create Task Directory — 2026-08-13T12:36:00.000Z

Task directory `tasks/task_1486_union_dues_membership_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T14:27:07.160Z

All three scaffold artifacts are written and lint-clean. Summary:

## Files written

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/SCAFFOLD.yaml` | 1128 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1122 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/SCAFFOLD_CORNER_DESIGN.yaml` | 2028 |

## Counts

- **Entities: 15** — Local, MemberClassification, Employer, Member, DuesAssessment, LedgerEntry (append-only), CheckoffRemittance, RemittanceLine, DelinquencyNotice, ObjectorCase, MemberTransfer, PerCapitaReport, Election, ElectionEligibility (immutable snapshot), AssessmentRun
- **State machines: 9** — incl. Member cyclic (ACTIVE→DELINQUENT→ACTIVE, SUSPENDED→ACTIVE, cap-driven EXPELLED branch), CheckoffRemittance parallel dims (status × dispute_status), ObjectorCase appeal cycle (REBATE_ISSUED→APPEALED→RATE_SET), MemberTransfer branching with supersede
- **Calculations: 8** — assessed_dues (provisional-vs-final, clamp branches), payment_waterfall, delinquency_evaluation, reinstatement_due (pinned evaluation order), remittance_reconciliation, objector_rebate (per-line-round-then-sum; projected-vs-actual), per_capita_tax (transfer-boundary snapshot), election_eligibility (inclusive 12-month date boundary)
- **Validations: 10 priority groups** (auth → ownership → existence → OCC → state → referential → temporal → constraint → fiscal)
- **Endpoints: 63** (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default, and a `POST /api/system/sweeps/delinquency` ops-run checkpoint)
- **Errors: 51** (all referenced by ≥1 validation/transition; one unreachable error — ERR_DISPUTE_UNRESOLVED — was found and removed during self-review)
- **Roles: 5** — ParentBodyAdmin/LocalAdmin/SecretaryTreasurer/OfficeClerk (opaque) + Member (entity_backed:Member); segregation of duties on remittance receive/post and per-capita create/approve
- **Difficulty design instances (§1.8): 18** — 2 per rule; differentiators: dual-variant on DuesAssessment vs ObjectorCase domains; combinatorial modes (a) vs (b) with literal one-cent rounding witness (1342 vs 1341); cascades of depth 4 (remittance post→ledger→arrears→member→notice) and depth 3 (sweep→notice→suspension→transfer-cancel); priority pairs state×temporal and referential×fiscal; boundaries at arrears == threshold and reinstatement total ± 1 cent; overlap semantics half-open (notices) vs closed-touching (elections); compensating invariants on money (post+void restores ledger sum 20000) vs headcount (transfer roundtrip conserves 3000 cents of per-capita)
- **Corner design instances (§1.9): 57 active + 6 excluded_because stubs** across all nine taxonomy sections
- **Concurrency rules: 2** true-race OCC entries (transfer create on Member.version, per-capita report create-with-supersede on Local.version), both exercised by 412 stale-version corner tests

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(712 §1.8+§1.9 calls scanned; the only fix cycle needed was renaming sub-resource parent path params to `{id}` for lint check (f).)

Additional self-checks passed: 81 unique instance names across both design files, zero unbound `${var}` placeholders, zero dangling grounds refs, no forbidden race vocabulary, all enum values producible, every formula-derived assert pre-computed to a literal.

## Step 3: Copy Shared Files — 2026-08-13T14:27:55.977Z

Copied `./INSTRUCTION.md` to `tasks/task_1486_union_dues_membership_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T14:50:28.920Z

PRD generation complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/workspace/PRD.md` — 353 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC (headers, 5 roles, per-role identity prose: `Member` entity-backed, 4 opaque roles), 2.2 API Response Structure (**verified byte-identical** to canonical `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC), 2.4 The Logical Clock (default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties (incl. explicit `updated_at`/`version` absence for `LedgerEntry`, `ElectionEligibility`, `AssessmentRun`), 2.6 Money/Precision/Append-Only Ledger, 2.7 OCC (both rules, exact error IDs + 412, "no other endpoint takes a version field"), 2.8 Segregation of Duties, 2.9 Validation Order (all 10 priorities with per-error HTTP statuses), 2.10 Nested Resource Resolution (left-to-right)
- §3 Business Logic — 9 subsections: 3.1 Locals & Classifications, 3.2 Members & Ledger/Waterfall, 3.3 Assessment Runs & Dues Calculation, 3.4 Checkoff Remittances (receive→lines→reconcile→dispute→resolve→post→void), 3.5 Delinquency/Notices/Suspension/Reinstatement, 3.6 Objector Cases & Rebates (actual vs projected variants), 3.7 Transfers, 3.8 Per-Capita Reporting, 3.9 Elections & Eligibility
- §4 Endpoint Definitions (4-column table, all 63 scaffold endpoints present, verified)
- §5 Error Code Catalogue (2-column table, all 51 errors)

**Zero-silence coverage audit (all PASS):**
- **Contract 1 (field names):** entities[].fields 84/84 present; endpoint inputs 49/49 present; query/output extras (`limit`, `offset`, sweep outputs, quote outputs, rebate-projection outputs, `current_utc`, etc.) 14/14 present; all path-param forms (`{id}`, `{employerId}`, `{noticeId}`, `{caseId}`, `{transferId}`, `{reportId}`) in §4. Missing: 0.
- **Contract 2 (rules):** all 10 validation priorities expressed in order (§2.9); 2/2 OCC rules with write-endpoint + `expected_member_version`/`expected_local_version` + exact error IDs; all state-machine transitions (9 machines, incl. parallel remittance `status`×`dispute_status` dims, dispute-only self-transition, supersede/cancel cascades) expressed; 8/8 calculations in precise prose (fallback chain, round-half-up-once at basis-point multiplication, waterfall bucket order with `created_at` tie-break, per-line round-then-sum rebate, strict-greater-than per-capita transfer boundary, inclusive election standing window at date granularity); all 51 error IDs appear in §2/§3 narrative; all role names and all 58 enum/state values present verbatim; sibling branches (provisional/final, actual/projected, clean/dispute reconcile, suspend/expel, ACTIVE/DELINQUENT withdrawal) rendered with equal density. Missing: 0.
- **Contract 3 (§3 path purity):** 538 backticked tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- No pseudocode operators (`==`, `>=`, `+=`, `min(`, etc.) and no fuzzy words ("approximately", "roughly", …) anywhere in the document.

One judgment call to flag: the scaffold's reconcile transition side effect says synthesized assessments for lined members use "gross 0 → floor dues" while the `remittance_reconciliation` calculation says synthesized assessments use the line's reported `gross_wages_cents`; I followed the calculation table (line's gross) for lined members and reserved "gross 0 → floor" for missing members at dispute resolution, which is the internally consistent reading. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened, and no sibling task directories were read.

## Steps 5+6: Generate Unit Tests & Implementation (concurrent) — 2026-08-13T15:48:32.355Z

### Step 5 (unit-test-generator subagent summary, verbatim):

Generation complete. Summary:

## Files written (21 files, 3696 lines)

**test_helpers/** (under `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/test_helpers/`):
- `types.py` (353) — 9 status enums + `UserRole`; 17 TypedDicts. Immutable records (`LedgerEntry`, `ElectionEligibility`, `AssessmentRun`) carry only `id` + `created_at` per the PRD common-fields exception.
- `api_client.py` (209) — `ApiClient(GenericApiClient)` with 62 endpoint methods (all PRD §4 routes incl. `/_clock/set_current_utc`).
- `api_errors.py` (125) — 52-error enum + HTTP status map registered via `set_error_http_status_map`.
- `assertions.py` (199) — per-entity structural assertions + money-consistency invariant; no over-demand of optional/computed fields.
- `factories.py` (106), `constants.py` (43) — payload factories; canonical PCT/FLAT local configs, `CLOCK_START_ISO`, `BASIS_POINTS_DENOMINATOR`, `MISSING_UUID`.
- `test_users.py` (51) — `TEST_USERS` shared headers for the 4 opaque roles + a non-ownership Member fallback; **per-instance builders** `make_member_headers(user_id)` (mandatory for the entity_backed Member role) plus per-role builders; named operator constants `OFFICE_CLERK_1/SECRETARY_TREASURER_1/LOCAL_ADMIN_1` so SoD tests can compare user ids across calls.
- `fixtures.py` (242) — composite drivers: `set_clock`, `run_period` (clock-to-period-01 + run), `drive_member_delinquent` (charge periods → sweep), `drive_member_suspended` (full notice→expire→sweep chain), remittance lifecycle helpers (receive as clerk_1, reconcile/resolve/post as st_1, void as admin_1), `make_transfer`/`make_percapita_report` (OCC version auto-fetched via GET), `make_objector_case`, `set_objector_rate`, `make_election`.
- `__init__.py` (38) — barrel re-export of framework + all helpers.

**test_suite/**: `conftest.py` (35) + 11 test files (88 tests, pytest-collected clean).

## Test counts
- **Queue A (Difficulty): 17/18 instances covered, 34 tests** (exactly 2 per instance).
- **Queue B (Corner): 54/58 non-stub instances covered, 54 tests** (1 each). All 6 `excluded_because` stubs verified to resolve to real difficulty instances; no tests emitted for them.

## Skip list (PRD-first filter failures — gaps left as gaps)
1. `Difficulty/combinatorial_formula/objector_rebate_round_per_line_then_sum` — asserted rebate 1342 (and `last_rebated_period` 2026-09, credit 341) contradicts PRD §3.6's inclusion window: with `rate_set_at` stamped at clock 2026-10-01, only FINAL periods ≥ 2026-10 qualify; the recipe's two FINALs (2026-08, 2026-09) are excluded, so the PRD-derived rebate is 0. Design chain is inconsistent with the PRD rule it grounds in.
2. `Corner/state_machines/objector_appeal_rebate_cycle` — same contradiction: asserted `cumulative_rebate_cents == 200` requires the 2026-08 FINAL to be included, but `rate_set_at` period is 2026-09 → PRD yields 0.
3. `Corner/calculations/objector_pct_boundaries_zero_and_hundred` — asserted pct-0 rebate 1000 fails the same window (PRD yields 0); the remaining asserts (pct-100 zero rebate, pct-101 error) don't carry the instance's distinguishing claim.
4. `Corner/state_machines/withdrawn_member_terminal_lockdown` — no PRD sentence binds any error to a payment attempted on a WITHDRAWN member (`ERR_MEMBER_TERMINAL_STATE` is PRD-bound only to objector filing and rebate issuance); not uniquely derivable.

Note: the sibling difficulty instance `objector_rebate_projected_vs_actual_diverge` **survives** because the projection read's actual-to-date figure is defined by PRD §3.6 as a "lifetime line-rebate sum … deliberately ignoring `last_rebated_period`" with no rate-set window.

## Stage 2 tag audit
- 88/88 tests carry exactly one `Design:` docstring line as the final docstring line; 0 untagged, 0 dual-tagged, 0 tags pointing at stubs or non-existent instances.
- Coverage: every covered difficulty instance has 2 tests; every covered corner instance has 1. Only the 4 deliberate skips show 0.
- Citation audit: 105 quoted PRD spans (≥8 words) all survive whitespace-normalized literal match against `workspace/PRD.md`.
- Zero `pytest.mark.skip/skipif/xfail`; zero "scaffold" mentions in generated code.

## Helper-layer design decisions
- **Identity threading**: Member-role calls always use `make_member_headers(member["id"])`; opaque-role SoD paths use fixed operator ids (`clerk_1` receives, `st_1` reconciles/posts/creates reports, `admin_1` approves/voids) so `received_by != posted_by` and `created_by != approved_by` hold by construction in happy-path fixtures, and the negative SoD tests swap in `make_secretary_treasurer_headers("clerk_1")` / `make_local_admin_headers("st_1")`.
- **Money**: integer cents throughout; no float helpers needed (PRD mandates integer cents); boundary values (17499/17500, 9999/10000) passed as literals.
- **Time**: all time-dependent state is driven via `set_clock()` against the PRD's logical clock; timestamp assertions (`cure_deadline`, `last_suspension_ended_at`) parse with `datetime.fromisoformat` and compare instants, since PRD pins the instant but allows millisecond serialization variance.
- **Ledger assertions** select entries by `entry_type` rather than positional index where the PRD's chronological ordering already guarantees the property (positional check retained only in the reverse-reachability test where the recipe asserts order directly).

### Step 6 (implementation-generator subagent summary, verbatim):

Implementation complete. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/workspace/implementation/`.

## Files written (paths + line counts)

| File | Lines |
|---|---|
| `implementation/start.sh` | 10 |
| `implementation/requirements.txt` | 1 |
| `implementation/app.py` | 64 |
| `implementation/db.py` | 67 |
| `implementation/errors.py` | 278 |
| `implementation/response.py` | 54 |
| `implementation/middleware.py` | 37 |
| `implementation/utils.py` | 122 |
| `implementation/serializers.py` | 86 |
| `implementation/routes/locals.py` | 284 |
| `implementation/routes/members.py` | 388 |
| `implementation/routes/remittances.py` | 359 |
| `implementation/routes/assessment_runs.py` | 87 |
| `implementation/routes/employers.py` | 42 |
| `implementation/routes/objector_cases.py` | 126 |
| `implementation/routes/transfers.py` | 114 |
| `implementation/routes/per_capita.py` | 56 |
| `implementation/routes/elections.py` | 116 |
| `implementation/routes/sweeps.py` | 25 |
| `implementation/routes/clock.py` | 20 |
| `implementation/services/dues.py` | 140 |
| `implementation/services/ledger.py` | 139 |
| `implementation/services/sweep.py` | 150 |
| `implementation/services/rebate.py` | 149 |

Plus two empty `__init__.py` package markers. Total ~2,914 lines. **All 63 scaffold endpoints implemented** (1 clock + 1 sweep + 61 business routes).

## Module structure

- `db.py` — in-memory store (empty at boot, no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, insertion sequence for created_at tiebreaks, RLock held per-request.
- `errors.py` — `ApiError` plus one factory per scaffold error_id with its exact HTTP status.
- `response.py` — envelope: `{meta: {api_request_id (req_…), api_request_timestamp (3-fractional-digit ISO)}, response_type: object|array|error, data}`; list responses add `limit/offset/total_count/has_more` into `meta`.
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (400 on missing/undeclared), per-endpoint role gating (403), Member-ownership check (403, evaluated before path existence on member-scoped paths).
- `services/` — `dues.py` (assessed_dues), `ledger.py` (posting + waterfall + auto-cure), `sweep.py` (delinquency sweep + transfer-cancel cascade), `rebate.py` (objector rebate both variants, per-capita count, election eligibility).

## Calculation → code mapping

- **assessed_dues** → `services/dues.py::compute_assessed`: fallback chain (classification ?? local), FLAT_RATE base = flat, PERCENTAGE_OF_GROSS base = `(gross*bp + 5000) // 10000` (exact integer round-half-up, applied once), then `max(base, floor)` / `min(·, cap)`; pins `rate_bp_applied` (null on FLAT), `flat_applied_cents` (null on PERCENTAGE), `min/max_applied_cents`. Provisional wage base = most-recent earlier FINAL's gross else 0 (`provisional_wage_base`); final variant at reconcile (line gross) or stale-finalize at a later run (gross 0), posting SUPPLEMENTAL_CHARGE/ADJUSTMENT_CREDIT deltas (`finalize_assessment`).
- **payment_waterfall** → `services/ledger.py::waterfall`: buckets ordered REINSTATEMENT_FEE (oldest first) then assessments (period ASC, created ASC); full replay in insertion order — charges open/grow their own bucket, credits fill earliest-open; `paid_cents` = min(allocated, assessed_cents); `arrears = max(0, Σamounts)`, `credit_balance = max(0, −Σ)`; VOID_REVERSALs negate naturally by sign (only CHECKOFF_CREDITs and finalize-deltas are reversed — the synthesized ASSESSMENT_CHARGE survives a void, per PRD's "negating each CHECKOFF_CREDIT and each finalize-delta entry").
- **delinquency_evaluation** → `services/sweep.py::run_sweep`: members in created_at ASC; aged = FINAL with bucket-remaining > 0 and period ≤ current − grace_periods (month arithmetic); over = arrears ≥ threshold (inclusive); ACTIVE→DELINQUENT + DRAFT notice (unless DRAFT exists), expired-window+over → EXPIRED + SUSPENDED or EXPELLED at `suspension_count+1 >= max_suspensions`, window-closed+under → CURED, SUSPENDED + `expel_after_months` calendar months (day-clamped) → EXPELLED; transfers cascade-cancelled (INITIATED/PENDING_TARGET on suspension, all non-terminal on expulsion).
- **reinstatement_due** → `members.py::reinstatement_quote`: arrears (pre-fee) → fee = base × suspension_count → total; POST reinstate posts REINSTATEMENT_FEE then DIRECT_PAYMENT, exact-amount match else `ERR_REINSTATEMENT_AMOUNT_MISMATCH`.
- **remittance_reconciliation** → `routes/remittances.py::reconcile`: roster re-validation first (422), then header balance (409, `header_variance_cents` persisted on failure), per-line finalize/synthesize-at-line-gross, variance + MATCHED/UNDER/OVER_DEDUCTED, `expected_total_cents` over roster (ACTIVE/DELINQUENT) with an assessment, `missing_member_ids` sorted by member created_at; clean → RECONCILED, else dispute NONE→DISPUTED on the parallel dimension. `resolve-dispute` finalizes missing members at floor (gross 0).
- **objector_rebate** → `services/rebate.py`: actual = Σ per-line `max(0, min(paid, assessed) − round_half_up(assessed·pct/100))` over FINALs with period > last_rebated_period (or ≥ period of rate_set_at when never rebated) and paid > 0 — round per line, then sum; projection = actual-to-date (periods ≤ current, ignoring last_rebated_period) + floor-dues rebate per remaining period of the current calendar year after the latest FINAL (floor = resolved flat on FLAT_RATE, min floor on PERCENTAGE_OF_GROSS, per PRD's literal wording).
- **per_capita_tax** → `services/rebate.py::per_capita_count`: base = current-local members ∪ completed transfers out with effective_period > P; exclude non-ACTIVE/DELINQUENT, per_capita_exempt classifications, and completed transfers in with effective_period > P (strict >, so effective == P counts at the target).
- **election_eligibility** → `services/rebate.py::evaluate_eligibility`: ordered reasons NOT_ACTIVE → ARREARS_OUTSTANDING → INSUFFICIENT_STANDING_MONTHS; date-granularity inclusive boundary (`ended + N months > cutoff` fails).
- **OCC** → `expected_member_version` on transfer create (412 `ERR_STALE_MEMBER_VERSION`), `expected_local_version` on per-capita create (412 `ERR_STALE_LOCAL_VERSION`); version increments once per affected member per request, and on every mutation including cascades.

## Verification

Four smoke suites (~196 assertions) run against fresh `bash start.sh` boots — all pass, covering: envelope/pagination shapes, RBAC + ownership, clock default/set, dues calc (floor/cap/override/both branches), runs + stale finalize, remittance full lifecycle (unbalanced, dispute, resolve, post, SOD, chronological/reverse-chronological guards, period lock, void compensation), delinquency boundaries (inclusive threshold, cure window half-open), suspension cap → expulsion, expel_after_months boundary, reinstatement quote/amount exactness, objector appeal cycle + rebate projection numbers, transfer OCC/supersede/complete-timing/per-capita boundary, election window overlap + standing-months inclusive boundary, and reboot-with-empty-store isolation.

## Step 7 — Test/iterate loop (2026-08-13)

**Iteration 1 sweep**: 8/8 rounds identical, 76/88 passed, 12 failed — all 12 on one signature: `AssertionError: id must be a UUID, got '<32-hex-dashless>'`.

**Diagnosis** (diagnostic protocol):
- STEP 1: PRD §2.5 states "The `id` is a server-minted UUID with no type prefix." Canonical UUID wire form (RFC 4122 / `str(uuid.uuid4())`) is dashed 8-4-4-4-12; the framework's `is_valid_uuid` requires it. Covered + uniquely derivable.
- STEP 3 (implementation bug): `workspace/implementation/utils.py::new_id` returned `uuid.uuid4().hex` (dashless). Fixed to `str(uuid.uuid4())`. No dashless dependencies anywhere (grep-verified).
- Latent test_helpers bug surfaced by the fix: `test_helpers/assertions.py` used `RemittanceStatus` in `assert_remittance` (line 119) without importing it (NameError, previously masked by the UUID assertion firing first). Added `RemittanceStatus` to the `.types` import.

**Iteration 2 sweep**: 8/8 rounds — 88/88 passed, 0 failed. Clean.

Tests deleted: none. No PRD-silence or unique-derivability violations found among failing tests.

## Step 7: Subagent returned summary (verbatim) — 2026-08-13T15:59:47.278Z

Clean 8-round parallel sweep achieved. Summary:

## Summary

**Iterations run:** 2 (sweep 1: 76/88 in all 8 rounds; sweep 2 after fixes: **88/88 in all 8 rounds, 0 failed**)

**Tests deleted:** none — every failing test traced to verbatim PRD rules with unique derivability.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/test_helpers/assertions.py` — added missing `RemittanceStatus` to the `.types` import. `assert_remittance` referenced it at line 119 without importing it (latent NameError, masked in sweep 1 only because the UUID assertion fires earlier in the same function).

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/workspace/implementation/utils.py` — `new_id()` returned `uuid.uuid4().hex` (dashless 32-char form); changed to `str(uuid.uuid4())` (canonical dashed form). PRD §2.5 states "The `id` is a server-minted UUID with no type prefix", and the standard wire serialization of a UUID is the dashed 8-4-4-4-12 form the framework's `is_valid_uuid` requires. Grep-verified no implementation code depended on the dashless shape (all 17 `new_id()` call sites just store the value).

**Failure signature (both root causes, 12 tests × 8 rounds):** every failure was `id must be a UUID, got '<dashless-hex>'` from entity-shape assertions (`assert_member`, `assert_assessment_run`, `assert_remittance`, `assert_election`, `assert_percapita_report`, `is_valid_uuid` on list items) across test files 01, 02, 03, 04, 09, 10, 11. Deterministic across all rounds — not flakiness.

## Step 8: Finalize PRD — 2026-08-13T16:03:45.162Z

Done. The diff is exactly one in-place sentence revision.

## Summary

**Line counts / delta:** PRD.md 353 lines; PRD_FINALIZED.md 353 lines; 0% line-count delta (one line revised in place at line 78).

**Changes (one bullet per change):**
- §2.5 Common Resource Properties — revise — appended ", rendered in the canonical dashed 8-4-4-4-12 hexadecimal form (e.g., `550e8400-e29b-41d4-a716-446655440000`)" to the `id` sentence — `implementation/utils.py:14-15` (`new_id()` returns `str(uuid.uuid4())`).

**Disposition of other step_7_diff items:** the `test_helpers/assertions.py` missing `RemittanceStatus` import is a pure fixture bug (latent NameError in test helper code, unrelated to any PRD statement) — no PRD change.

**Per-edit pre-edit search log:**
- Edit 1 (§2.5 `id` serialization):
  - (a) Subject: wire format of server-minted resource `id` values (and, by copy, all foreign keys holding them).
  - (b) Paths enumerated: `implementation/utils.py:14-15` (sole minting point); all 16 `new_id()` call sites (`routes/locals.py:50,127,185,254`; `routes/members.py:70,308,358`; `routes/employers.py:25`; `routes/remittances.py:68,133`; `routes/assessment_runs.py:78`; `routes/elections.py:74`; `services/ledger.py:25`; `services/sweep.py:132`; `services/dues.py:89`) — each stores the value verbatim as an entity `id`; `serializers.py` (passes `entity["id"]` through untouched); `db.py` (ids used as opaque dict keys); path-parameter lookups (e.g., `routes/locals.py:22-23` `db.store.locals.get(local_id)`) treat incoming ids as opaque strings — grep for `is_valid_uuid`/`uuid.UUID(` across `implementation/` returned zero hits, confirming no inbound UUID-format validation; `response.py:16` `api_request_id` (`req_` + hex) is governed by §2.2, not §2.5, so unaffected.
  - (c) Wording adjustment: scoped the claim to the *rendering* of the server-minted id ("rendered in the canonical dashed ... form") rather than any validation claim, since the implementation never validates incoming path ids as UUIDs; kept it inside the existing §2.5 sentence so it covers all resources uniformly, matching the single shared `new_id()` used by every entity type.

## Step 9: Complete PRD — 2026-08-13T16:24:59.304Z

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1486_union_dues_membership_administration/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (which existed and was used as the source).

**Size:** source `PRD_FINALIZED.md` 353 lines / 60,949 chars → `PRD_COMPLETED.md` 353 lines / 63,954 chars. Char-delta **+3,005**, zero lines added/removed (all changes are in-paragraph inserts/revisions; no new sections).

**Counts:** 20 ambiguity-pins (inserts), 3 mismatch-revisions.

### Ambiguity pins (insert)

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], negative offset to 0), not rejected — `implementation/utils.py:98-103`
- §2.4 — insert — ambiguity — calendar-month addition clamps day-of-month to target month length (Jan 31 + 1mo → Feb 28/29), governing sweep expulsion and election standing-months — `implementation/utils.py:65-70`, `services/sweep.py:62`, `services/rebate.py:147`
- §2.9 step 6 — insert — ambiguity — added `ERR_DISPUTE_NOT_ACTIVE` to the state-guard precedence list — `implementation/errors.py:150-152`, `routes/remittances.py:258`
- §2.9 step 7 — insert — ambiguity — added `ERR_LOCAL_NOT_FOUND` to the body-reference HTTP-422 existence errors (member/remittance/assessment-run/sweep bodies) — `implementation/errors.py:79-80`, `routes/members.py:57-58`, `routes/remittances.py:60-61`, `routes/assessment_runs.py:26-27`, `routes/sweeps.py:22-23`
- §3.1 — insert — ambiguity — closing a non-ACTIVE local is rejected with `ERR_LOCAL_NOT_ACTIVE`; closure gates exactly the enumerated creations while member registration, remittance receipt, and the delinquency sweep remain permitted on a CLOSED local — `implementation/routes/locals.py:91-92`, `routes/members.py:56-58`, `routes/sweeps.py:21-24`
- §3.2 — insert — ambiguity — direct payments are not gated on member status (ACTIVE through EXPELLED alike) — `implementation/routes/members.py:111-125`
- §3.3 — insert — ambiguity — stale provisionals are swept only among the local's current members, and stale finalizations run before new provisionals are created, so a just-finalized zero-wage FINAL feeds the new provisional's wage base — `implementation/routes/assessment_runs.py:41-72`
- §3.4 — insert — ambiguity — remittance `period` is validated for YYYY-MM format only (`ERR_INVALID_PERIOD`), no clock-period constraint — `implementation/routes/remittances.py:62`
- §3.4 — insert — ambiguity — a line whose member already holds a FINAL assessment for the period leaves it untouched; variance computed against its existing assessed amount — `implementation/routes/remittances.py:165-166`
- §3.4 — insert — ambiguity — remittance-level `expected_total_cents`/`header_variance_cents` are null and `missing_member_ids`/`auto_cured_member_ids` are empty lists until reconcile (posting for auto-cured) populates them — `implementation/routes/remittances.py:75-78`
- §3.4 — insert — ambiguity — `resolution_note` is accepted but not persisted — `implementation/routes/remittances.py:252-258`
- §3.5 — insert — ambiguity — sweep suspension expires every expired SENT notice (a still-open SENT notice stays SENT); the not-over path cures every SENT notice — `implementation/services/sweep.py:89-115`
- §3.5 — insert — ambiguity — the sweep's defensive DELINQUENT→ACTIVE return also cures every SENT notice and deletes every DRAFT notice — `implementation/services/sweep.py:116-124`
- §3.5 — insert — ambiguity — expulsion clears `suspended_since` to null, never sets `last_suspension_ended_at`, and touches no notices — `implementation/services/sweep.py:63-67`
- §3.5 — insert — ambiguity — withdrawal is available only from ACTIVE/DELINQUENT: SUSPENDED → `ERR_MEMBER_STATE_FORBIDDEN`, WITHDRAWN/EXPELLED → `ERR_MEMBER_TERMINAL_STATE` — `implementation/routes/members.py:133-136`
- §3.5 — insert — ambiguity — the reinstatement quote, like reinstatement, requires SUSPENDED (`ERR_MEMBER_NOT_SUSPENDED`) — `implementation/routes/members.py:158-159`
- §3.6 — insert — ambiguity — a zero computed rebate posts no `REBATE_CREDIT` entry; `last_rebated_period` is unchanged when no assessment is included; the case still moves to `REBATE_ISSUED` — `implementation/routes/objector_cases.py:92-99`
- §3.6 — insert — ambiguity — rebate projection on a never-rated (FILED) case returns zero for both figures; with no FINAL assessment the projection starts at the current clock period — `implementation/services/rebate.py:64-76`
- §3.7 — insert — ambiguity — malformed or pre-current `effective_period` is rejected with `ERR_INVALID_PERIOD` (422) — `implementation/routes/members.py:346-349`
- §3.8 — insert — ambiguity — report creation validates `period` as well-formed YYYY-MM (`ERR_INVALID_PERIOD`); no clock-period constraint — `implementation/routes/locals.py:169-174`

### Mismatch revisions (revise)

- §3.2 — revise — mismatch — payment-waterfall bucket population: "non-terminal dues assessments" → assessments in any status, PROVISIONAL and FINAL alike (FINAL buckets are what `paid_cents` on finalized assessments and rebate math rely on) — `implementation/services/ledger.py:67-77`
- §3.4 — revise — mismatch — `expected_total_cents`/`missing_member_ids` population: "all roster members holding a non-terminal assessment" → roster members in ACTIVE or DELINQUENT status holding an assessment in either PROVISIONAL or FINAL state, valued at the assessed amount current at reconcile (final for lined members, provisional for unlined), computed once and not recomputed at dispute resolution — `implementation/routes/remittances.py:218-233`
- §3.7 — revise — mismatch — completion guard order: three guards listed state→period→standing → four guards in impl order: `ERR_TRANSFER_STATE_FORBIDDEN` → `ERR_NOT_GOOD_STANDING` (member not ACTIVE) → `ERR_TRANSFER_NOT_READY` → `ERR_ARREARS_OUTSTANDING` — `implementation/routes/transfers.py:88-97`

Everything else in the implementation (endpoint table, roles, OCC scope, segregation of duties, error catalogue, state machines, dues/rebate/per-capita/eligibility formulas, response envelope, immutable-resource field exceptions) was verified to be already uniquely pinned by the PRD and left unchanged.
