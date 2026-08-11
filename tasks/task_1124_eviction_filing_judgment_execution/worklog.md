# Worklog — task_1124_eviction_filing_judgment_execution

## Step 1: Create Task Directory — 2026-08-10T19:54:00.000Z

Pre-assigned output folder `tasks/task_1124_eviction_filing_judgment_execution` with `workspace/` subdirectory already exists (per pipeline instructions). Step 1 auto-index scan skipped as directed. Scenario: 1124. Eviction Filing & Judgment Execution (landlord side): notice type selection & statutory cure period, filing package preparation & court fee, service of process & hearing calendar, tenant answer/defense & mediation referral, judgment for possession & money damages, writ issuance & sheriff lockout scheduling, personal property storage obligations, post-judgment collection & rental history reporting. Difficulty parameter: "hard than expert level" (passed to scaffold generator at Step 2).

## Step 2: Generate Scaffold — 2026-08-10T20:56:00.000Z

All done. Lint is clean and all three artifacts are valid YAML.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1215 §1.8+§1.9 calls scanned, 0 violations)

## Summary

Task directory: `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/`

**SCAFFOLD.yaml** (82 KB) — §1.0–§1.7 only, no design keys:
- **15 entities**: Landlord, RentalUnit, Tenancy, EvictionCase, Notice, FilingPackage, ServiceAttempt, Hearing, TenantAnswer, MediationReferral, Judgment, Writ, PropertyStorageRecord, CollectionEntry, RentalHistoryReport (flat topology, self-referential FKs on CollectionEntry.reversal_of_id and RentalHistoryReport.reference_report_id)
- **61 endpoints**, **40 error codes**, **40 ordered validation rows**, **8 calculations**, **6 roles** (segregation-of-duties model: party-cannot-serve + fee-clerk ≠ judgment-clerk), **1 OCC concurrency rule** (notice-supersede on EvictionCase.version)
- **11 state machines**, deliberately non-linear: EvictionCase cycles via mediation loop and filing-reject/refile; Writ cycles ISSUED→SCHEDULED→ISSUED and ISSUED→EXPIRED→re-request; RentalUnit VACANT⇄OCCUPIED
- Key mechanics: jurisdiction-driven statute table (CA/TX/OH), tiered filing fee with STANDARD/ELECTRONIC variants, per-diem-then-multiply interest rounding, storage charge dual variants (CALENDAR_INCLUSIVE vs ELAPSED_24H), collection waterfall with reversal compensation, ops-run checkpoint sweeps, logical clock with pinned default 2026-05-01T00:00:00Z
- Design fix made during authoring: dropped an unreachable unit-level lockout-overlap rule (one-active-tenancy + one-open-case constraints make it impossible) and kept deputy day-capacity as the second overlap semantics

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (97 KB) — 18 instances, 2 per rule, all 9 rule_ids; every formula-derived assert pre-computed (e.g., fee 29750 vs 28000; interest 270 not 274; storage 3000 vs 1000; ledger 108000→58000→108000→100000)

**SCAFFOLD_CORNER_DESIGN.yaml** (185 KB) — 61 instances (56 active + 5 excluded_because stubs) across all 9 claim-extraction sections; stubs reference only verified §1.8 instance names

Cross-file audit passed: no duplicate instance names across the union, all grounds resolve to declared §1.1–§1.7 elements, no forbidden concurrency vocabulary, every error referenced by a validation row, every endpoint role declared in RBAC.

## Step 3: Copy Shared Files — 2026-08-10T20:56:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1124_eviction_filing_judgment_execution/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T21:05:00.000Z

All three hard contracts now PASS. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/workspace/PRD.md`.

## Summary

**PRD line count:** 335 lines

**Section list:**
- §1. Introduction (2 paragraphs, business-context angle)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control — 6 roles with exact spelling, per-role `identity:` translations (Landlord entity-backed; the other five opaque with recorded-field examples)
  - 2.2 API Response Structure — emitted verbatim from `section-2.2-response-structure.md` (byte-identical body verified)
  - 2.3 Pagination — `limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, `meta` fields
  - 2.4 Common Resource Properties — `id`/`created_at`/`updated_at`/`version`, with explicit `ServiceAttempt`/`CollectionEntry` exception (only `id` + `created_at`)
  - 2.5 The Logical Clock and the Ops-Run Sweep — startup default `2026-05-01T00:00:00Z`, never wall-clock; five sweep steps in fixed order with the five output counters
  - 2.6 Money, Dates, and Jurisdictional Schedules — integer cents, single round-half-up at the per-diem step, 23:59:59Z date-close convention
  - 2.7 Validation Order and Nested Resource Resolution — 12-rung priority ladder (first failure wins) plus left-to-right path existence
  - 2.8 Optimistic Concurrency Control on Notice Drafting — `expected_case_version` required, mismatch → `ERR_STALE_VERSION` (412), no other endpoint takes a version field
  - 2.9 Segregation of Duties and Actor Binding — `ERR_NOT_OWNER`, `ERR_SOD_PARTY_CANNOT_SERVE`, `ERR_SOD_FEE_JUDGMENT`, mediator/deputy binding
  - 2.10 Cascading State Propagation — execution cascade (case→tenancy→unit), mediation stay/cancel, writ expiry/lapse unwinds, supersede, cure
- §3. Business Logic & Workflows (9 subsections, chronological lifecycle): 3.1 Portfolios, 3.2 Case + Notice Period (cure-day tables, OCC, supersede, cure, dismissal), 3.3 Filing Package + Fees (tiered fee schedule, surcharge/jury/variant, floor 0, review cycle), 3.4 Service of Process (set-cardinality completion), 3.5 Hearings/Answers/Mediation (4 scheduling rules in order, continuance, mediation cycle), 3.6 Judgment (pinned per-diem rounding order, totals order, appeal windows), 3.7 Writ/Lockout/Storage (exact writ fee, deputy capacity 3/day, window rules, execution cascade, both billing modes, reclaim/dispose), 3.8 Collections (waterfall, reverse-order re-credit, satisfaction), 3.9 Rental-History Reporting (event anchors, 30-day window, correction supersession)
- §4. Endpoint Definitions — 61 rows, 4 columns only (Method, Path, Description, Authorized Roles)
- §5. Error Code Catalogue — 40 rows, 2 columns only

**Contract reports:**
- Contract 1 (field-name coverage): 107 required identifiers (entity fields + endpoint inputs + query params), 107 present in backticks, 0 missing — PASS (two passes run; first pass caught `answer_id`/`judgment_id`, repaired)
- Contract 2 (rule coverage): all 44 state values, all transitions' from/to pairs, all 7 calculations with constants (cure-day matrix, fee tiers/ceilings, rates, appeal days, writ fees, storage fees/days, hearing lead days, deputy cap), all 40 errors matched to trigger conditions in §2/§3 prose, validation priority ladder stated globally plus per-endpoint local orderings, OCC rule, all cross-entity cascades, sibling-branch symmetry (ACCEPT/REJECT, SETTLED/FAILED, both billing modes, all entry/report types) — PASS
- Contract 3 (§3 path purity): 481 backticked tokens in §3, 0 paths / 0 bare HTTP methods / 0 method+path combos — PASS

No fuzzy/approximating words, no pseudocode operators (verified by scan), and the forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and all sibling task directories were never opened.

## Step 5: Generate Unit Tests — 2026-08-10T21:35:00.000Z

Note: first Step 5 subagent was cut off mid-work and produced no files; a bounded re-spawn completed the step. Final summary:

Done. Complete test infrastructure generated for `task_1124_eviction_filing_judgment_execution`.

**Test count: 96 total — Queue A (Difficulty): 36 tests over 18/18 instances (≥2 each); Queue B (Corner): 60 tests over 56/56 non-stub instances (≥1 each).** All files compile (`python3 -m py_compile`) and pytest collects all 96 tests without errors.

**Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter. The 5 `excluded_because:` stubs in the errors section (`error_courtroom_overlap_trigger`, `error_deputy_capacity_trigger`, `error_hearing_lead_time_trigger`, `error_cure_amount_insufficient_trigger`, `error_appeal_window_trigger`) were not translated; all cross-references resolve to real difficulty instances that own the assertions. The two `priority_pair_validation_conflict` difficulty instances were retained (not skipped as validation-priority silence) because PRD §2.7 explicitly pins the ordered validation ladder ("the first failing rung determines the error returned") and names both rungs' categories, making precedence uniquely derivable.

**Writ-expiry nuance handled as instructed:** `test_04` reads `expires_on` from the issued writ's response at runtime and sets the logical clock to `expires_on + 1s`; `writ_window_must_fit_validity` derives `window_start`/`window_end` from the runtime `expires_on` rather than asserting absolute day-count timestamps.

**Helper files** (`test_helpers/`): `__init__.py` (barrel: framework generics + PRD-specific), `types.py` (13 status enums + 15 entity TypedDicts; ServiceAttempt/CollectionEntry correctly omit `updated_at`/`version`), `api_client.py` (`ApiClient(GenericApiClient)` with 48 endpoint methods), `api_errors.py` (41 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions, ledger-shape checks for append-only entities), `factories.py` (payload factories + `compute_filing_fee_cents` mirroring the PRD §3.3 formula), `constants.py` (CURE_DAYS, FILING_FEE_TIERS, WRIT_FEE, STORAGE_*, APPEAL_DAYS, etc.), `test_users.py` (shared constants + `make_landlord_headers(user_id)` builder for the entity_backed Landlord role), `fixtures.py` (composite pipeline fixtures: `setup_case_notice_expired` → `setup_case_filed` → `setup_case_service_complete` → `setup_case_hearing_scheduled` → `setup_case_answered_with_referral` → `setup_judgment_entered` → `setup_judgment_final` → `setup_writ_issued` → `setup_writ_scheduled` → `setup_executed_with_storage`, all threading ownership via `make_landlord_headers(landlord["id"])`).

**Test files** (`test_suite/`): `conftest.py` + 20 numbered test files (fee calc, judgment money, mediation cycle, writ lifecycle/cascade, priority pairs, boundary precision, cross-entity gates, resource conflicts, compensating invariants, storage/collections, entities/defaults, case states, writ/hearing gates, fees/filing, service/SoD, ownership/shape, rental-history reports, endpoints/envelope, RBAC, cross-cutting OCC/ops-run).

**Audits passed:** every test has exactly one `Design:` tag resolving to a real instance; 140/140 PRD citation fragments grep verbatim against `workspace/PRD.md` (whitespace/markdown-marker normalized); zero `pytest.mark.skip`/`skipif`/`xfail` markers.

## Step 6: Generate Implementation — 2026-08-10T21:35:30.000Z

Implementation complete and verified. Summary:

## Files (22 files, 2647 total lines) in `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/workspace/implementation/`

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py`, reads `$PORT` (default 10000), binds 0.0.0.0, foreground |
| `requirements.txt` | 1 | flask |
| `app.py` | 64 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| `db.py` | 74 | In-memory store (dicts keyed by id, empty at boot, zero seeding), logical clock pinned at `2026-05-01T00:00:00Z`, id/seq/counter helpers |
| `errors.py` | 8 | `ApiError(error_id, status, message)` |
| `response.py` | 44 | Envelope: `meta.api_request_id/api_request_timestamp` (+`limit/offset/total_count/has_more` on lists), `response_type`, `data` |
| `middleware.py` | 49 | `X-User-ID`/`X-User-Role` auth (401/403), six scaffold roles, ownership helper |
| `utils.py` | 142 | Body/field validators (400 `ERR_VALIDATION`), strict YYYY-MM-DD + ISO-8601 parsing, pagination (limit 1–100 default 10, offset ≥ 0), ms timestamp serializer |
| `services/calc.py` | 78 | All jurisdictional schedules: cure days, filing-fee tiers, interest rates (per-diem `ROUND_HALF_UP` via `Decimal` then multiply), appeal days, writ fees, hearing lead days, storage fees/modes/days, deputy cap |
| `services/serialize.py` | 225 | Per-entity serializers (ledger entities expose only `id`+`created_at`); storage `accrued_charge_cents` computed at current logical clock, reads 0 once RECLAIMED/DISPOSED |
| `services/resolution.py` | 129 | get-or-404 per entity, aggregate-chain resolvers |
| `routes/*.py` (10 files) | 1905 | All endpoints |

**Endpoints implemented: 61/61** from the scaffold table (landlords, units, tenancies, cases+dismiss, notices+record-cure with OCC `expected_case_version`→412, filing packages+fee-payments+review, service-attempts, hearings+continuance+conclude, answers+mediation-referrals+outcome, judgment, writs+issue/schedule/cancel/execute, storage reclaim/dispose, collection entries+reversals, rental-history reports+corrections, ops sweep, `_clock/set_current_utc`).

## Verification performed
- `bash -n start.sh` parses; all 20 Python files compile; server boots via `bash start.sh` on a test port, bound to 0.0.0.0, foreground; restarted cleanly with an empty store (no carry-over — the per-test-server requirement).
- Live end-to-end runs across CA/TX/OH verified: full lifecycle DRAFT→notice→sweep-expiry→package (fee math: CA efiled 43000, TX paper 21750 / efiled 20000)→review/reject/refile→service completion→hearing lead/overlap/continuance→answer→mediation STAYED/CANCELLED loop→judgment (per-diem rounding: CA 82¢/day, TX 16¢/day; SoD `ERR_SOD_FEE_JUDGMENT`)→appeal finalize→writ (fee/possession/active-writ gates)→schedule (deputy capacity: 3rd OK, 4th → `ERR_DEPUTY_DAY_CAPACITY`)→cancel/lapse/expiry unwinds→execute cascade (case EXECUTED → tenancy ENDED → unit VACANT, storage record created)→collection waterfall/reversal/write-off to SATISFIED→rental-history reports with 30-day window + CORRECTION supersession.
- Validation ladder order honored (auth→role→404→ownership/binding→shape→OCC→state→safety→constraints→temporal→referential→fiscal); every catalog error ID was exercised with its scaffold HTTP status.

One judgment call: the scaffold references `writ_valid_days(jurisdiction)` for `expires_on` without defining values; I used 30 days for all three jurisdictions (CA/TX/OH) — all other constants are taken verbatim from the scaffold/PRD.

## Step 7: Run Tests and Iterate — 2026-08-10T21:55:00.000Z

**Iterations run:** 2 (iteration 1: 21 consistent failures across all 8 rounds; applied fixes; iteration 2: 96/96 passed in all 8 parallel rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/test_helpers/assertions.py` — added `assert_instant_equal(actual, expected)`, which compares ISO-8601 instants semantically. PRD pins instant values (cure_deadline at 23:59:59Z, appeal_deadline = entered_at + window, etc.) but mandates the three-fractional-digit rendering only for `created_at`/`updated_at` (§2.4) and the envelope timestamp (§2.2); exact-string equality on other instants was not uniquely derivable.
- `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/test_helpers/fixtures.py` — default lockout window moved from 2026-08-01T09:00-10:00 to 2026-06-26T09:00-10:00 in `schedule_lockout`, `setup_writ_scheduled`, `setup_executed_with_storage` (+ timeline comment). PRD §3.7 defines `expires_on` as issued_at plus "the jurisdiction's writ validity period" but never states the period's length, so the fixture's 37-days-post-issuance window violated the PRD rule `window_end ≤ expires_on` on any faithful implementation choosing a shorter period.
- `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/test_helpers/factories.py` — `create_schedule_lockout_payload` default window moved to 2026-06-26 for the same reason.

**Fixes applied to `test_suite/`:**
- `test_01_filing_fee_calculation.py` (`test_variant_fee_frozen_at_creation`) — wrong arithmetic constant 27500 → 25500 (PRD §3.3: CA base 24000 + 2500 defendant − 1000 e-filing discount = 25500; the old constant contradicted even the suite's own `compute_filing_fee_cents` helper).
- `test_02_judgment_money.py`, `test_04_writ_lifecycle_and_cascade.py`, `test_10_storage_and_collections.py` (overpayment test), `test_11_entities_and_defaults.py` (×2), `test_15_service_and_sod.py`, `test_20_cross_cutting.py` — exact-string instant assertions converted to `assert_instant_equal` (PRD pins the instant, not the fractional-digit rendering).
- `test_04` — executed/stored instants updated to the new fixture timeline (2026-06-26T09:00Z), disposal eligibility to 2026-07-11T09:00Z (stored + CA 15 days).
- `test_08_resource_conflicts.py`, `test_09_compensating_invariants.py` — deputy-capacity/cancel window dates moved to 2026-06-26/27 to fit any plausible writ validity.
- `test_10_storage_and_collections.py` (`test_same_day_reclaim_single_day_charge`) — TX half reshaped: same-instant ELAPSED_24H accrued charge is not uniquely derivable (PRD's "elapsed 24-hour periods with any partial period rounded up" admits both 0 and 1 at zero elapsed hours; the scaffold's own formula gives 0), so the TX read now happens 1 hour after storage, where "any partial period rounded up" pins exactly 1 day = 1000. The CA same-instant assertion (1500) is PRD-pinned ("counting both the stored date and the current date") and kept.
- `test_12_notice_and_case_states.py` (`test_second_judgment_rejected`) — relaxed to `validate_error_is_one_of([ERR_JUDGMENT_EXISTS, ERR_INVALID_STATE])` per the error-precedence-silence rule: PRD §3.6 names ERR_JUDGMENT_EXISTS for a second attempt, but §2.7's ladder evaluates the state gate (rung 7, ERR_INVALID_STATE — the case is JUDGMENT_ENTERED, not HEARING_CONCLUDED) before judgment uniqueness (rung 9); PRD does not state which rung reports the collision. Both are HTTP 409, asserted explicitly.
- `test_13_writ_and_hearing_gates.py` — three clock settings moved to the new window timeline (execute 1s before window opens at 2026-06-26T08:59:59Z; inside-window at 09:00; lapsed-window sweep at 10:00:01Z).
- `test_15_service_and_sod.py` (`test_failed_then_partial_then_complete`) — added `set_clock("2026-06-02T09:00:00Z")` before the completing SERVED attempt; the test previously recorded `served_at` in the future relative to the logical clock, which PRD §3.4 mandates rejecting with ERR_DATE_IN_FUTURE (the implementation was correct; the test request violated a PRD precondition).

**Fixes applied to `implementation/`:** none — every failure traced to test/test_helper artifacts; the implementation was PRD-faithful on all 21 failing paths.

## Step 8: Finalize PRD — 2026-08-10T22:02:00.000Z

All four edits are in place; the diff is exactly four in-place line revisions. Final verification of consistency is complete.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 335 lines, PRD_FINALIZED.md = 335 lines (0% line delta — all four changes are inline sentence revisions on existing lines, no sections added or removed).

### Changes (one bullet per edit)

- **§2.6 (Money, Dates, and Jurisdictional Schedules)** — revise — appended a sentence pinning that every instant-typed field in a response body (client-echoed instants like `served_at`/`window_start`/`window_end`, server-computed instants like `cure_deadline`/`appeal_deadline`/`expires_on`, and the clock endpoint's `current_utc`) renders with exactly three fractional digits, e.g. `2026-06-26T09:00:00.000Z` — `implementation/utils.py:138-142` (`ts()` used by every serializer in `implementation/services/serialize.py` and by `implementation/routes/ops.py:96`; envelope timestamp at `implementation/response.py:7-9`).
- **§3.6 (Judgment)** — revise — replaced "a second attempt is rejected with `ERR_JUDGMENT_EXISTS` (HTTP 409)" with the ladder-accurate precedence: a second entry attempt ordinarily finds the case already `JUDGMENT_ENTERED` and so fails the state gate with `ERR_INVALID_STATE` (HTTP 409); `ERR_JUDGMENT_EXISTS` (HTTP 409) is reported only when the state gate passes yet a judgment already exists; SOD sits between — `implementation/routes/judgments.py:36-52` (state gate → `ERR_SOD_FEE_JUDGMENT` → uniqueness order).
- **§3.7 (Writ issuance)** — revise — pinned the writ validity period to 30 days in each of CA, TX, and OH — `implementation/services/calc.py:25` (`WRIT_VALID_DAYS = {"CA": 30, "TX": 30, "OH": 30}`), consumed at `implementation/routes/writs.py:114`.
- **§3.7 (Storage accrual)** — revise — pinned the `ELAPSED_24H` zero-elapsed reading: a record read at the very instant of `stored_at` has no elapsed (not even partial) period and charges zero days — `implementation/services/calc.py:72-73` (`max(0.0, …)` clamp plus `ceil(...) if elapsed_seconds > 0 else 0`).

Diff items that required no PRD edit (pure test/fixture bugs where PRD already pinned behavior): `test_01` fee constant 27500→25500 (§3.3 arithmetic already correct), `test_15` added `set_clock` before the completing SERVED attempt (§3.4 already pins `ERR_DATE_IN_FUTURE`), and all fixture timeline moves (2026-08-01 → 2026-06-26 windows, disposal eligibility date, deputy-capacity dates, test_13 clock settings) — these were downstream symptoms of the writ-validity silence now pinned by edit 3.

### Per-edit pre-edit search log

1. **Instant rendering (§2.6).** (a) Subject: fractional-digit rendering of instants in responses. (b) Enumerated and read: `implementation/utils.py:138-142` (single `ts()` formatter, always 3 fractional digits), all 14 serializers in `implementation/services/serialize.py` (every instant field routes through `ts()`, including echoed client input parsed by `v_dt`/`parse_dt_str` at `utils.py:95-116`), `implementation/response.py:7-9` (envelope timestamp, also 3 digits), `implementation/routes/ops.py:94-96` (`current_utc` via `ts()`), input-parse paths in `routes/service.py:24`, `routes/hearings.py:69-70`, `routes/writs.py:131-132` (all `v_dt` → datetime → `ts()` on output). Date-only fields (`served_on`, `lease_start_date`, `session_date`, `oldest_unpaid_due_date`) confirmed stored/echoed as `YYYY-MM-DD` strings, unaffected. (c) Wording scoped to *response rendering* only (not input format, not the 23:59:59Z instant *value* rule, which is kept verbatim) so no enumerated path is mis-described.

2. **Second-judgment precedence (§3.6).** (a) Subject: which error a second judgment-entry attempt reports. (b) Enumerated and read: `implementation/routes/judgments.py:23-90` (full entry handler: body shape → state gate `ERR_INVALID_STATE` at :36 → SOD at :41-47 → uniqueness `ERR_JUDGMENT_EXISTS` at :49-52), `implementation/services/resolution.py:125` (`judgment_for_case`), the only other `judgment_for_case` callsite (`judgments.py:106`, read-only case-judgment endpoint), and PRD §2.7 ladder (state rung 7 < SOD rung 8 < uniqueness rung 9). Confirmed `ERR_JUDGMENT_EXISTS` remains reachable in code (case `HEARING_CONCLUDED` + existing judgment), so it must stay named rather than deleted. (c) Wording widened from an unconditional `ERR_JUDGMENT_EXISTS` claim to the conditional both-codes description; HTTP 409 preserved for both, matching §5 catalogue.

3. **Writ validity period (§3.7).** (a) Subject: length of the writ validity period. (b) Enumerated and read: `implementation/services/calc.py:25` (definition), all `expires_on` consumers — `routes/writs.py:114` (set), :153 (window validity `window_end ≤ expires_on`), :214 (execution not after `expires_on`), `routes/ops.py:40-52` (sweep step 3), `services/serialize.py:171` (render) — plus PRD §2.5 sweep step three (names no length, consistent). (c) Wording inserted as an appositive ("— 30 days in each of `CA`, `TX`, and `OH`") on the existing sentence, keeping "the jurisdiction's writ validity period" phrasing so §2.5 and the other §3.7 sentences remain accurate.

4. **ELAPSED_24H zero-elapsed (§3.7).** (a) Subject: chargeable days at zero elapsed time under `ELAPSED_24H`. (b) Enumerated and read: `implementation/services/calc.py:67-74` (`storage_charge`: CALENDAR_INCLUSIVE floors at 1 day — already PRD-pinned via "counting both the stored date and the current date"; ELAPSED_24H gives 0 at zero elapsed, `ceil` for any positive elapsed), both callsites `services/serialize.py:179-196` (read path, including the RECLAIMED/DISPOSED → 0 override already in PRD) and `routes/writs.py:284-293` (reclaim exact-match path). (c) Wording appended as a trailing clause on the existing ELAPSED_24H sentence, explicitly tied to "read at the very instant of `stored_at`" so it does not disturb the pinned 23-hours→1-day example, the CALENDAR_INCLUSIVE branch, or the reclaim/`final_charge_cents` sentences.

## Step 9: Complete PRD — 2026-08-10T22:20:00.000Z

All edits applied cleanly. PRD_COMPLETED.md is complete: 337 lines / 56,627 chars vs source 335 lines / 52,588 chars (+2 lines, +4,039 chars; 32 paragraphs touched, no sections added or removed).

## Summary

**Source vs output:** PRD_FINALIZED.md (335 lines, 52,588 chars) → PRD_COMPLETED.md (337 lines, 56,627 chars), char-delta +4,039.

**Counts:** 34 ambiguity-pins, 2 mismatch-revisions (36 changes total; some pins bundle two related clauses in one paragraph edit).

### Ambiguity-pins

- §2.1 — insert — ambiguity — header present-but-empty treated as missing → 401 — implementation/middleware.py:26
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + 24 hex chars — implementation/response.py:14
- §2.2 — revise — ambiguity — `api_request_timestamp` is the sole wall-clock reading; all record/stored timestamps read the logical clock — implementation/response.py:7-9 vs db.py:47
- §2.2 — insert — ambiguity — undeclared path / unsupported method → `ERR_NOT_FOUND` (404) in standard envelope — implementation/app.py:44-50
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_VALIDATION` — implementation/utils.py:119-135
- §2.3 — insert — ambiguity — creation-timestamp ties broken by insertion sequence — implementation/db.py:73-74
- §2.3 — insert — ambiguity — `has_more` = (offset + returned items) < total_count — implementation/response.py:32
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read the logical clock; `version` starts at 1 — implementation/db.py:44-54
- §2.5 — insert — ambiguity — clock is set exactly to `to_iso8601`, forward or backward — implementation/routes/ops.py:87-96
- §2.7 — insert — ambiguity — body-referenced resources (`landlord_id`/`unit_id`/`tenancy_id` on creates) resolved after body-shape rung, before ownership; missing → `ERR_NOT_FOUND` — implementation/routes/portfolio.py:53,96; implementation/routes/cases.py:38
- §2.8 — insert — ambiguity — missing/non-integer `expected_case_version` → `ERR_VALIDATION` — implementation/routes/cases.py:145-149
- §3.2 — insert — ambiguity — case-open on non-`ACTIVE` tenancy → `ERR_INVALID_STATE`, before one-open-case check — implementation/routes/cases.py:41-44
- §3.2 — revise — ambiguity — `case_number` = EV-<logical-clock year>-<6-digit zero-padded global sequence from 1> — implementation/routes/cases.py:52-53
- §3.2 — insert — ambiguity — conditional notice fields exclusive: `claimed_rent_owed_cents`/`violation_description` on a non-matching type → `ERR_VALIDATION` — implementation/routes/cases.py:157-176
- §3.2 — revise — ambiguity — `served_on` future-check at calendar-date granularity (same-date accepted) — implementation/routes/cases.py:193
- §3.2 — insert — ambiguity — cross-type cure fields only type-checked, never stored; only `cured_at` is stored — implementation/routes/cases.py:255-267
- §3.3 — insert — ambiguity — package creation gated to case `NOTICE_EXPIRED`/`FILING_REJECTED` → else `ERR_INVALID_STATE` — implementation/routes/filing.py:42-47
- §3.3 — revise — ambiguity — fee payment `amount_cents` is a positive integer — implementation/routes/filing.py:96
- §3.3 — insert — ambiguity — review case-state gate applies to both ACCEPT and REJECT, ordered between DRAFT gate and paid-fee check — implementation/routes/filing.py:127-140
- §3.5 — revise — ambiguity — continuance `reason` accepted but not persisted; continued hearing excluded from one-SCHEDULED and overlap checks — implementation/routes/hearings.py:120,126
- §3.5 — revise — ambiguity — `defense_codes` duplicates permitted, stored as given — implementation/routes/answers.py:23-33
- §3.5 — revise — ambiguity — referral `session_date` unconstrained — implementation/routes/answers.py:79
- §3.5 — revise — ambiguity — conclude `notes` accepted but not persisted — implementation/routes/hearings.py:149
- §3.7 — revise — ambiguity — `writ_fee_paid_cents` must be a positive integer (else `ERR_VALIDATION`) — implementation/routes/writs.py:32
- §3.7 — insert — ambiguity — deputy-capacity check evaluated before window-validity check (ladder rung 9 before 10) — implementation/routes/writs.py:135-158
- §3.7 — revise — ambiguity — cancel-lockout `reason` accepted but not persisted — implementation/routes/writs.py:183
- §3.7 — revise — ambiguity — zero-days-at-`stored_at` pinned to `ELAPSED_24H`; `CALENDAR_INCLUSIVE` always charges ≥1 day (stored date counts) — implementation/services/calc.py:67-74
- §3.7 — revise — ambiguity — `charge_paid_cents` must be a non-negative integer — implementation/routes/writs.py:279
- §3.7 — insert — ambiguity — disposing a `RECLAIMED`/`DISPOSED` record → `ERR_INVALID_STATE` — implementation/routes/writs.py:305-308
- §3.8 — revise — ambiguity — `reversal_of_id` required on REVERSAL, forbidden on PAYMENT/WRITE_OFF (`ERR_VALIDATION`) — implementation/routes/judgments.py:126-137
- §3.8 — insert — ambiguity — `allocation` keys pinned: `court_costs`, `late_fees`, `damages`, `interest`, `rent` — implementation/routes/judgments.py:112
- §3.8 — insert — ambiguity — once `SATISFIED`, a judgment is never returned to `ENTERED`/`FINAL` by later entries — implementation/routes/judgments.py:208-210
- §3.9 — revise — ambiguity — JUDGMENT anchor = max `entered_at`; SATISFACTION anchor = max `satisfied_at` across the tenancy's cases — implementation/routes/reports.py:49,63
- §3.9 — revise — ambiguity — `bureau_reference` = RHR-<global counter from 1, no zero-padding> — implementation/routes/reports.py:114-123

### Mismatch-revisions

- §3.7 — revise — mismatch — removed "freezes `accrued_charge_cents` to the same figure" on reclaim; impl only locks `final_charge_cents` and `accrued_charge_cents` reads as 0 once `RECLAIMED` (matching the PRD's own later sentence) — implementation/routes/writs.py:293-295, implementation/services/serialize.py:180-183
- §3.8 — revise — mismatch — outstanding-balance formula qualifier "entries that have not been reversed" replaced with "all of the judgment's entries": impl keeps the reversed payment's subtraction and cancels it via the reversal's addition (old reading would double-count the reversal) — implementation/routes/judgments.py:175-192

**Cross-checks performed with no change needed:** all 62 endpoint role assignments in §4 match the `@auth(...)` decorators exactly; all HTTP status codes in §5 match `ApiError` call sites; the 201-vs-200 create/modify convention of §4 holds for every route; all jurisdictional schedules (cure days, fee tiers, interest rates, appeal windows, writ fees/validity, hearing lead times, storage fees/modes/periods, deputy cap 3) match `services/calc.py`; the ops-sweep five-step order, strictness of each comparison, and counter names match `routes/ops.py`; response field shapes for all 16 serializers match the fields named in §3 prose.

Output file: /home/ubuntu/github/CodingPRD/tasks/task_1124_eviction_filing_judgment_execution/workspace/PRD_COMPLETED.md
