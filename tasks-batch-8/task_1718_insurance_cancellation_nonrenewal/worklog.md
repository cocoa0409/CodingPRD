# Worklog — task_1718_insurance_cancellation_nonrenewal

## Step 1: Create Task Directory — 2026-08-14T10:28:00.000Z

Task directory `tasks/task_1718_insurance_cancellation_nonrenewal/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (index 1718 explicitly assigned; no scan performed, per instructions).

## Step 3: Copy Shared Files — 2026-08-14T10:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1718_insurance_cancellation_nonrenewal/workspace/INSTRUCTION.md` (1424 bytes). Done out of order while Step 2 subagent runs — Step 3 has no dependency on Step 2 output.

## Step 2: Generate Scaffold — 2026-08-14T10:57:00.000Z

Done. All three scaffold artifacts generated and lint-clean.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

### §1.1–§1.7 counts

- Entities: 11 (StateFilingProfile, Policyholder, InsuredInterest, Policy, CancellationCase, NonrenewalCase, NoticeRecord, PremiumLedgerEntry, ReinstatementRequest, AppealCase, RegulatoryReport)
- State machines: 8 (Policy cyclic with reinstatement loop; CancellationCase and NonrenewalCase branching with rescission; AppealCase fork UPHELD/OVERTURNED with divergent side effects; NoticeRecord, ReinstatementRequest with auto-EXPIRED sweep; RegulatoryReport; StateFilingProfile)
- Calculations: 4 (`return_premium` dual-variant pro-rata/short-rate with pinned double-rounding; `notice_window` nested-max over ground tier × recipient class; `reinstatement_fee` tiered with pinned eval order; `nonrenewal_volume` period aggregation with left-closed/right-open windows)
- Validations: 11 priority levels (auth → existence → state → segregation-of-duties → statutory grounds → notice windows → temporal → uniqueness → referential → OCC fiscal)
- Endpoints: 45 (including test-driving `POST /carrier/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Errors: 29
- Roles: 3 (ComplianceOfficer opaque, Underwriter opaque, Policyholder entity_backed:Policyholder) — segregation_of_duties role model
- Concurrency rules: 2 OCC rules on `Policy.version` (cancellation-case create, reinstatement create)

### §1.8 / §1.9 counts

- Difficulty instances: 18 (9 rules × 2), each with distinguishing aspects naming the required distinction (different entity domains for dual-variant; modes (a) vs (b) for combinatorial; different entities for non-linear machines; depth-3 vs depth-2 cascades from different triggers; different error-category pairs; different metrics/endpoints for boundaries; different entity pairs; different interval semantics; different conserved quantities)
- Corner instances: 47 total = 40 active test recipes + 7 `excluded_because:` stubs citing §1.8 instances; all instance names unique across both files

### Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(45 endpoints, 11 entities, 18 §1.8 + 40 §1.9 instances, 622 calls scanned)

### Coverage audit notes

- All 29 error codes are referenced by at least one validation/transition, and each has either an active trigger instance or an `excluded_because` stub.
- Numeric asserts were pre-computed in Python: pro-rata 60164 vs short-rate 54148 (120000-cent policy, 182/365 elapsed, 10% penalty); double-rounding case 51800 → 38850 (25% penalty); notice window 2026-08-05 + max(30,45) = 2026-09-19; nonrenewal deadline 2026-12-31 − 60 = 2026-11-01; reinstatement tiers at lapse 10/11/31 → 0/2500/5000 cents; window edge 45 ok / 46 rejected; ledger cascade entries −13900 / −13400 / +13400.
- OCC payloads always use `${var}` or `${var} - 1`, never literals; every `${var}` is bound by an earlier `captures:` in the same instance; every captured field resolves to §1.5 outputs.
- FK reverse-reachability: fixed during lint iteration — renamed sub-resource parent params to `{id}` (`/carrier/policies/{id}/interests`, `/carrier/policies/{id}/ledger-entries`), added `insured_interest_id?` filter to `GET /carrier/notices`, `cancellation_case_id?` to `GET /carrier/reinstatement-requests`, and added `GET /carrier/cancellation-cases/{id}/ledger-entries`.
- Hard-difficulty features per the request: clock-sweep-driven deferred state changes with mail-window gating (notice RETURNED_UNDELIVERABLE blocks effectiveness), a bounded cancellation→reinstatement cycle consuming a finite slot budget, segregation-of-duties chains across three workflow steps, dual premium-return variants with pinned rounding order, and boundary clusters on notice deadlines, reinstatement windows, and period-report windows.

Orchestrator verification: all three files exist and parse as YAML; SCAFFOLD.yaml top-level keys exclude both design keys; each design file carries exactly its single required top-level key.

## Step 4: Generate PRD — 2026-08-14T11:15:00.000Z

All verifications pass. The PRD is complete and ships.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/workspace/PRD.md` — 293 lines.

**Section list:**
- §1. Introduction (2 paragraphs — regulatory-stakes angle, logical clock + roles + money/days conventions)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control — 2.2 API Response Structure (verified byte-identical to the canonical block) — 2.3 Pagination — 2.4 The Logical Clock and Scheduled Compliance Sweeps — 2.5 Common Resource Properties (incl. PremiumLedgerEntry's absent `updated_at`/`version`) — 2.6 Date Arithmetic and Monetary Precision — 2.7 Nested Resource Retrieval — 2.8 Optimistic Concurrency Control — 2.9 The Premium Ledger — 2.10 Regulatory Volume Reporting — 2.11 Validation Order and Error Precedence (all 11 priority tiers with their error IDs)
- §3. Business Logic & Workflows (8 subsections, lifecycle-chronological): 3.1 State Filing Profiles — 3.2 Policyholders, Policy Issuance, and Insured Interests — 3.3 Opening a Cancellation Case — 3.4 Approval, Statutory Notices, and Cancellation Effectiveness — 3.5 Withdrawal and Rescission — 3.6 The Nonrenewal Path — 3.7 Reinstatement After Cancellation — 3.8 Appeals and the Overturn of a Cancellation
- §4. Endpoint Definitions (45 rows, 4 columns) · §5. Error Code Catalogue (29 rows, 2 columns, all HTTP statuses match scaffold)

**Hard-contract results (all PASS):**
- Contract 1 Field-Name Coverage: 64/64 entity fields, 42/42 endpoint input/output identifiers (incl. `expected_policy_version`, `reason`, `notices`, `decision`, `to_iso8601`, `current_utc`), 9/9 path params — 0 missing. (First scan reported a false FAIL due to fenced JSON blocks shifting backtick pairing; re-ran with fenced blocks stripped → PASS.)
- Contract 3 §3 Path Purity: 327 backticked tokens scanned in §3, 0 path/method violations.
- §2.2: byte-identical to `section-2.2-response-structure.md`.

**Zero-Silence Rule coverage audit (Contract 2 walk — all expressed verbatim in prose):**
- **Validations priority:** all 11 tiers stated as an explicit ordered gauntlet in §2.11, with masking semantics ("a failure at any tier masks every later tier", OCC last).
- **OCC (2 rules):** §2.8 names both write operations (open cancellation case, submit reinstatement request), `expected_policy_version`, mismatch → `ERR_STALE_VERSION` (412), plus each rule's stale-data rationale; no race-timing framing.
- **State machines:** all 21 transitions across 8 entities expressed with from/to states, actors, preconditions paired to error IDs, and side effects — including the two rescind sibling branches (`APPROVED` vs `NOTICE_SENT` with its `ERR_ALREADY_EFFECTIVE` clock bound), both appeal decisions with equal density, and the NoticeRecord undeliverable → sweep-blocking cascade (`ERR_NOTICE_NOT_MAILED`, policy stays `CANCEL_PENDING` until a replacement notice is dispatched).
- **Calculations (4):** return premium (term/elapsed days, clamp, single-rounding unearned figure, then second rounding after penalty, mandatory order, both variants and when each applies, strictly-smaller short-rate property); notice windows (nonpayment vs other-grounds base tier, `INSURED_REQUEST` on the other-grounds tier, mortgagee-day max only when interests exist, deadline = term end minus notice days, both boundary inclusivities — on-deadline mailing on time, exactly-earliest effective date permitted); reinstatement fee (eligibility-first/fee-second ordering, tiers 10 days/0 cents, 30 days/2,500 cents, beyond 30 days/5,000 cents, boundary falls to lower tier); volume aggregation (all three counters, pinned-profile join, left-closed/right-open month window, auto-created `OPEN` rows).
- **Endpoints side effects:** every declared `Policy.version` bump, all ledger postings (`WRITTEN`, return entries, `REINSTATEMENT_FEE`, compensating `RETURN_PRO_RATA`), all report counter increments with auto-create, `requested_on_date`/`requested_by_role`/`submitted_on_date`/`filed_on_date`/`decided_on_date` stamping, and the audit-trail-preserving `EFFECTIVE` case on reinstatement.
- **Field structured content:** all defaults stated (`version_note` empty, `loan_number` empty, `rescinded_reason` empty, `reinstatements_used` 0, `cancellation_effective_date` unset, `lapse_flag` false, `decided_on_date` unset, profile born `DRAFT`); all 46 enum values present verbatim; all 29 error IDs appear in §2/§3 narrative; `LAPSE_FEE` enumerated as an entry kind without inventing a posting trigger (scaffold specifies none).
- **Cross-entity cascades and sibling symmetry:** sweep-driven policy/case/report mutations fully stated; cancellation vs nonrenewal dispatch rules given parallel density with their differing statutory clocks (`ERR_NOTICE_PERIOD_SHORTFALL` vs `ERR_NONRENEWAL_NOTICE_LATE`).

## Step 5: Generate Unit Tests — 2026-08-14T11:52:00.000Z

Generation complete. Final report:

### Files written

**`test_helpers/`** (9 files): `__init__.py` (barrel export), `types.py` (11 entity TypedDicts — PremiumLedgerEntry correctly omits `updated_at`/`version` per its append-only common-fields exemption — plus 12 status/role enums), `api_client.py` (42 endpoint methods, one per PRD endpoint row), `api_errors.py` (29 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (11 entity assertions + ledger invariant checkers), `factories.py` (input-only payload factories), `constants.py` (fee tiers, lapse threshold, clock start), `test_users.py` (TEST_USERS + mandatory `make_policyholder_headers(id)` for the entity-backed Policyholder role), `fixtures.py` (5-tier composites: `setup_active_policy`, `open_cancellation_case`, `approve_cancellation`, `dispatch_cancellation_notices`, `cancel_policy_effective` full lifecycle walk, `submit_reinstatement`, `file_appeal_under_review`, `find_report`).

**`test_suite/`** (11 files): `conftest.py` + `test_01_profiles_and_issuance.py` through `test_10_rbac_and_auth.py`.

### Test counts
- **Total: 75 tests.** Queue A (Difficulty): **36 tests** — all 18 instances × exactly 2 tests. Queue B (Corner): **39 tests** — all 39 non-stub instances × 1 test; 7 `excluded_because:` stubs not translated (all pointers verified resolving).

### Instances skipped (two-condition filter)
- **Corner/entities/computed_fields_ignore_client_input_on_create** — fails unique derivability: the instance itself concedes two acceptable outcomes ("rejected ERR_INVALID_REQUEST ... or the values are ignored"), and no PRD sentence states how unknown keys on cancellation-case creation are handled. A PRD-only reader could legitimately ship either.

### PRD-vs-instance corrections applied (not skips)
1. **Difficulty/.../policy_issuance_gated_on_profile_active** — instance asserts `ERR_INVALID_STATE`; PRD §3.2 verbatim states issuance against a non-ACTIVE profile "is rejected as malformed with `ERR_INVALID_REQUEST`". Tests assert the PRD-derived `ERR_INVALID_REQUEST`.
2. **Corner/state_machines/rescind_after_effectiveness_rejected** — by the time the clock passes the scheduled date the sweep has already moved the case to EFFECTIVE, so PRD's tier-4 state rule (`ERR_INVALID_STATE`) and the calendar rule (`ERR_ALREADY_EFFECTIVE`) both plausibly fire and PRD doesn't commit to precedence → used `validate_error_is_one_of` per the error-precedence silence pattern (both are 409).
3. **Corner/complexity_layers/occ_policy_version_increments_on_case_create** — the recipe's second create-with-stale-version would hit tier-9 `ERR_CANCELLATION_ALREADY_OPEN` before tier-11 OCC; the test withdraws the first case first so `ERR_STALE_VERSION` is the uniquely-derived outcome.
4. Fixture-date plumbing fixes where recipe dates contradicted their own profile constants (asserted literals unchanged): double-rounding instance uses `other_grounds_notice_days: 20` so scheduled 2026-06-15 is legal; nonrenewal-volume instance advances the clock to 2026-06-01 before dispatching notices mailed 2026-06-01; the late-nonrenewal test sets the clock to the mailing date so only the deadline rule can fire.

### Self-audit results
- **Stage 1**: all files compile and import against the installed framework; OCC payloads always capture version from live GETs (initial version value never assumed).
- **Stage 2 tag audit (scripted)**: 75/75 tests carry exactly one `Design:` line as the final docstring line; every tag resolves to a real instance with correct rule_id/section; no stubs translated; every difficulty instance has ≥2 tests; every non-stub corner instance has ≥1 test.
- **PRD-citation pass (scripted)**: every docstring's quoted PRD text was grep-verified verbatim against PRD.md — all pass. Citations are rule-bearing sentences (error IDs, thresholds, transitions), not endpoint titles. No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T11:52:00.000Z

Both ports closed (exit 7 = connection refused), all files compile. Done.

### Summary

Complete Python + Flask implementation for task 1718 (Insurance Cancellation & Nonrenewal Compliance) at `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/workspace/implementation/`.

#### Files written
- `app.py` — Flask app, blueprint registration, error handlers (ApiError → envelope; 404/405 → ERR_NOT_FOUND), `0.0.0.0:$PORT`
- `db.py` — in-memory dicts only (11 entity tables), empty at boot, no seeding
- `clock.py` — logical clock, default `2026-08-01T00:00:00Z`, never wall-clock
- `errors.py` — all 28 error IDs with exact HTTP statuses from SCAFFOLD §1.6
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (3-fractional-digit ISO), `response_type`, `data`; pagination `limit`/`offset`/`total_count`/`has_more` in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (tier 1) + role gating (tier 2), roles spelled exactly `ComplianceOfficer`/`Underwriter`/`Policyholder`
- `util.py` — id/timestamp stamps (`id`, `created_at`, `updated_at`, `version=1`), `touch()` mutation bump, body/field/enum/date validation (ERR_INVALID_REQUEST), left-to-right path resolution, pagination parsing
- `services/domain.py` — calculations (double-rounding `return_premium`, `notice_window`, tiered `reinstatement_fee`), ledger posting, report auto-creation/increment, notice-set validation, and the four clock sweeps (effectiveness, expiry, reinstatement expiry, lapse flags)
- `routes/` — 10 blueprints: clock, state_profiles, policyholders, policies (+interests +ledger), cancellation_cases (+case ledger), nonrenewal_cases, notices, reinstatement_requests, appeals, regulatory_reports
- `start.sh`, `requirements.txt`

#### Endpoint count
45 routes covering all 43 endpoint-table entries (43 unique paths; the interest list and policy-ledger share the `/carrier/policies/{id}` prefix as distinct rules).

#### start.sh
Guards the dependency install (`if ! python3 -c "import flask"`) so per-test reboots skip pip, then `exec python3 app.py` in the foreground. `app.py` binds `0.0.0.0` on `int(os.environ.get("PORT", "10000"))`.

#### Boot smoke test
Started on a free port, hit `/carrier/state-profiles` (auth gate → ERR_MISSING_AUTH_CONTEXT; then 201 create), shut down cleanly. Full E2E verified live: cancellation flow matching the corner-design worked example (refund 13400, version 1→4, report auto-created), short-rate double-rounding (4537 = round(10000·184/365)·0.9), OCC 412, SoD 403 on approve and appeal-decide, ground-role mismatch, profile conflict, duplicate policy number, notice-set incomplete, undeliverable-blocked sweep, appeal OVERTURNED compensating ledger entry (+11900) with policy restore, report finalize gating, lapse_flag at >30 days, and a fresh reboot confirming the store restarts empty and the clock returns to its default.

Note: Steps 5 and 6 ran concurrently in a single message (physical isolation — test_suite/ did not exist when impl-gen started).

## Step 7: Run Tests and Iterate — 2026-08-14T12:10:00.000Z

All 8 rounds pass cleanly with 75/75 tests passing. The task is complete.

### Summary

- **Iterations run**: 2 (initial sweep + 1 fix-and-rerun cycle).

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**: None.

- **Fixes applied to `test_suite/`**: 3 test setups corrected (all PRD-faithful, no assertion weakening):

  1. `test_suite/test_03_approval_and_notices.py::test_notice_period_shortfall_for_mortgagee_rejected` — Test bug: clock was set to 2026-08-05 but the mortgagee notice was mailed 2026-08-06 (in the future), so the implementation correctly raised `ERR_MAILING_DATE_IN_FUTURE` before reaching the shortfall check. Fix: keep clock at 2026-08-05 for case open (so `earliest_effective_date`=2026-09-19 still holds), then advance clock to 2026-08-06 before dispatch. Now mailed_on=2026-08-06 is "today" (not future) and 2026-08-06 + 45 = 2026-09-20 > scheduled 2026-09-19, exercising the shortfall rule the test was designed to verify (PRD §3.4).

  2. `test_suite/test_07_reinstatement.py::test_lapse_at_tier1_boundary_free_and_tier2_edge_2500` — Test bug: called `_cancelled_policy("WA", ...)` twice in one test; PRD §3.1 enforces "At most one profile per `state_code` may be `ACTIVE` at any moment", so the second profile activation correctly raised `ERR_STATE_PROFILE_CONFLICT`. Fix: second call now uses `"OR"` instead of `"WA"`.

  3. `test_suite/test_07_reinstatement.py::test_reinstatement_on_exact_window_last_day_admitted` — Same pattern: two `_cancelled_policy("WY", ...)` calls in one test. Fix: second call now uses `"VT"` instead of `"WY"`.

- **Fixes applied to `implementation/`**: None — the implementation was correct in all three cases; all failures were test-side setup bugs that violated PRD-stated preconditions (future mailing date; duplicate ACTIVE state profile).

Final state: 8/8 rounds × 75/75 tests passing.

## Step 8: Finalize PRD — 2026-08-14T12:20:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/workspace/PRD_FINALIZED.md` and is **byte-identical to `PRD.md`** — zero edits applied, because every Step 7 item was a pure test-side fixture bug against behavior the PRD already pins uniquely.

### Summary

- **Line counts / %-delta**: PRD.md = 293 lines; PRD_FINALIZED.md = 293 lines; delta = 0 (0.0%). `diff` confirms identical content.
- **Changes**: none.

### Per-item reasoning (why no edit was warranted)

1. **`test_03_approval_and_notices.py::test_notice_period_shortfall_for_mortgagee_rejected`** — The test bug was mailing the mortgagee notice "in the future" relative to the set clock, so the implementation correctly raised `ERR_MAILING_DATE_IN_FUTURE` before reaching the shortfall check. Both rules are already pinned verbatim in PRD §3.4 (line 167: "No `mailed_on_date` may lie later than the current clock date (`ERR_MAILING_DATE_IN_FUTURE`). And each notice must leave enough statutory runway… `ERR_NOTICE_PERIOD_SHORTFALL`") and both errors share tier 7 of §2.11 in the same order the implementation checks them. Verified against impl `workspace/implementation/routes/cancellation_cases.py:209-219` (future check at :216-217, shortfall check at :218-219, base-tier vs. `mortgagee_notice_days` selection at :209-214). No PRD silence.

2. **`test_07_reinstatement.py::test_lapse_at_tier1_boundary_free_and_tier2_edge_2500`** — The test bug was calling `_cancelled_policy("WA", …)` twice in one test, and the fixture activates a fresh state profile per call, tripping the correct `ERR_STATE_PROFILE_CONFLICT` guard. PRD §3.1 (line 145) already pins this verbatim: "At most one profile per `state_code` may be `ACTIVE` at any moment… rejected with `ERR_STATE_PROFILE_CONFLICT`" (also §2.11 tier 9). Verified against impl `workspace/implementation/routes/state_profiles.py:112-118`. The fee tiers actually under test are pinned in §3.7 (line 195). No PRD silence.

3. **`test_07_reinstatement.py::test_reinstatement_on_exact_window_last_day_admitted`** — Identical pattern: duplicate `"WY"` profile activation; fixed to `"VT"`. The window-boundary behavior under test is already pinned in §3.7 ("a `lapse_days` that exceeds the profile's `reinstatement_window_days` is rejected" — i.e., lapse == window is admitted). No PRD silence.

### Pre-edit search log

No edits were committed, so no pre-edit searches were triggered. The verification reads above (cancellation dispatch path, state-profile activation path, nonrenewal parallel path at `workspace/implementation/routes/nonrenewal_cases.py:58-69,159-163`, and the test fixtures) were performed to confirm each Step 7 item traces to a fixture bug rather than a PRD gap — confirmed in all three cases.

## Step 9: Complete PRD — 2026-08-14T12:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1718_insurance_cancellation_nonrenewal/workspace/PRD_COMPLETED.md` is written (copied from PRD_FINALIZED.md, then 22 inline edits; no new sections, no restructure).

**Size**: PRD_FINALIZED.md 293 lines / 46,107 chars → PRD_COMPLETED.md 295 lines / 49,506 chars (+2 lines, +3,399 chars).

**Counts**: 17 ambiguity-pins, 5 mismatch-revisions.

**Change log** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl evidence):

- §2.1 — insert — ambiguity — empty/whitespace `X-User-ID` and unrecognized `X-User-Role` count as malformed → `ERR_MISSING_AUTH_CONTEXT` — implementation/middleware.py:16-24
- §2.1 — revise — mismatch — PRD claimed ownership checks on "any resource that references a Policyholder"; impl enforces ownership only on cancellation-case creation, reinstatement submission, appeal filing (→ `ERR_FORBIDDEN_FOR_ROLE`); reads and other actions unchecked — routes/cancellation_cases.py:57, routes/reinstatement_requests.py:51, routes/appeals.py:41-44
- §2.2 — insert — ambiguity — general malformed-body rule (non-JSON, unknown fields, missing required, wrong type/out-of-vocabulary → `ERR_INVALID_REQUEST`); undefined route/unsupported method → `ERR_NOT_FOUND` — implementation/util.py:53-74,131-146; app.py:46-53
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; sort ties broken by insertion order; `has_more` ≡ offset + returned < total_count — util.py:157-181; response.py:39
- §2.4 — insert — ambiguity — clock accepts any parseable ISO-8601 instant; never required to move forward — implementation/clock.py:23-27; routes/clock_routes.py:16-25
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — util.py:32-39
- §2.9 — insert — ambiguity — unset `cancellation_case_id` serialized as JSON `null` — services/domain.py:129-141
- §2.9 — insert — ambiguity — pinned `effective_date` per posting event (WRITTEN→term_start_date; return→scheduled_effective_date; REINSTATEMENT_FEE→approval clock date; compensating→decision clock date and carries the case's `cancellation_case_id`); per-case ledger listing uses the same effective_date/created_at ordering — routes/policies.py:67; domain.py:299-305; routes/reinstatement_requests.py:140-145; routes/appeals.py:124-131; routes/cancellation_cases.py:255
- §3.1 — insert — ambiguity — non-two-ASCII-letter `state_code` → `ERR_INVALID_REQUEST` — routes/state_profiles.py:20,46-47
- §3.2 — insert — ambiguity — nonexistent `policyholder_id`/`state_profile_id` at issuance → `ERR_INVALID_REQUEST` (not `ERR_NOT_FOUND`) — routes/policies.py:31-36
- §3.3 — insert — ambiguity — pinned concrete guard order on case opening: ground/role → ownership → permissibility → ACTIVE → exclusivity → version guard — routes/cancellation_cases.py:52-77
- §3.4 — revise — mismatch — "exactly one notice per insured interest" → set-equality coverage with duplicate interest notices permitted (each entry creates a record); extra policyholder notice or unresolvable `insured_interest_id` also → `ERR_NOTICE_SET_INCOMPLETE` — services/domain.py:189-263
- §3.4 — insert — ambiguity — entries vetted in payload order, future-date rule before runway rule per entry — routes/cancellation_cases.py:209-219
- §3.4 — insert — ambiguity — dispatch responds with paginated list envelope of created NoticeRecords in payload order — routes/cancellation_cases.py:221-242
- §3.4 — revise — mismatch — removed "blocked case is surfaced with `ERR_NOTICE_NOT_MAILED`" and "until a replacement notice has been dispatched" (impl never raises it; re-dispatch impossible past APPROVED); now: sweep leaves case `NOTICE_SENT`/policy `CANCEL_PENDING` and re-evaluates each advance — domain.py:274-306; routes/cancellation_cases.py:197-198
- §3.4 — revise — mismatch — "always strictly smaller" SHORT_RATE claim → "never larger" (second rounding can leave the figure unchanged) — domain.py:108-112
- §3.6 — revise — mismatch — nonrenewal dispatch set rule mirrors revised cancellation coverage rule — routes/nonrenewal_cases.py:158 + domain.validate_notice_set
- §3.6 — insert — ambiguity — deadline comparison is the only calendar check (no future-date rule) on nonrenewal dispatch; same paginated list response — routes/nonrenewal_cases.py:161-186
- §3.7 — insert — ambiguity — case/policy pair mismatch → `ERR_INVALID_REQUEST`; non-EFFECTIVE named case → `ERR_INVALID_STATE`, both before the window check — routes/reinstatement_requests.py:44-59
- §3.7 — insert — ambiguity — reinstatement approval does not clear `lapse_flag`; only the lapse sweep flips it, and only while CANCELLED — routes/reinstatement_requests.py:132-138; domain.py:349-358
- §3.8 — insert — ambiguity — `filed_by` inconsistent with caller role → `ERR_FORBIDDEN_FOR_ROLE` — routes/appeals.py:35-38
- §3.8 — insert — ambiguity — OVERTURNED on an EFFECTIVE case also clears the policy's `cancellation_effective_date` — routes/appeals.py:134-135

**Not pinned deliberately** (impl exhibits no single behavior to pin): the placement of malformed-body validation relative to §2.11 tiers is inconsistent across endpoints in impl (body-first on top-level creates, existence-first on nested/action endpoints), so ordering of `ERR_INVALID_REQUEST` against other tiers is left unpinned rather than falsified.
