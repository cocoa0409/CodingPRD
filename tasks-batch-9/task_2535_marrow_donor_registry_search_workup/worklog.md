# Worklog — task_2535_marrow_donor_registry_search_workup

## Step 1: Create task directory — 2026-09-03T07:23:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2535_marrow_donor_registry_search_workup` and its `workspace/` subdirectory. Index 2535 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-03T09:26:00.000Z

All three artifacts are complete and the linter is clean.

## Output files

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2871 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2308 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5395 | `scaffold_corner_design` |

## SCAFFOLD.yaml surface

14 entities · 11 state machines · 2 `concurrency_rules` · 9 calculations · 55 ordered validations · 47 endpoints · 66 error codes · 5 roles (TransplantCoordinator, DonorRegistryLiaison, MedicalDirector, CollectionCenterOps, RegistryOperations). Profile: `workflow_orchestration` / `temporal_windowing`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, `immediate` consistency.

## Design index instance counts

- **§1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`**: 19 instances across all 9 rule_ids (>=2 per rule).
- **§1.9 `SCAFFOLD_CORNER_DESIGN.yaml`**: 73 instances (50 with full `test_recipe`, 23 `excluded_because` stubs) across all nine guide sections — entities 12, state_machines 17, calculations 13, validations 9, endpoints 6, errors 6, rbac 4, cross-cutting complexity layers 5, consistency model 1.
- 92 instance names total, all unique across both files; every stub cites an existing §1.8 instance by name and carries no `test_recipe`.

## Verification

- `python3 -c "import yaml; yaml.safe_load(...)"` passes on all three files.
- `scaffold_lint.py` -> `VERDICT: clean lint` over 1108 scanned §1.8+§1.9 calls (47 endpoints, 14 entities); all calls conform to §1.5 and every §1.1 FK has reverse-reachability.
- Independent cross-check: all 66 catalog error ids are referenced by at least one design instance (the only unreferenced `ERR_` token is `ERR_XXX`, the response-envelope placeholder).

## Notable design points in this session's work

- Final `errors` instances close the two hardest-to-reach codes: `ERR_PRODUCT_DOSE_INADEQUATE` (cd34 1.50 vs `MIN_CD34_E6_PER_KG` 2.00) and `ERR_PRODUCT_VIABILITY_EXPIRED`, which requires the product to actually arrive *before* `must_infuse_by` (a late DELIVERED event discards the shipment instead) with an adequate dose so priority 39 doesn't mask priority 47, then the clock advanced exactly one second past `must_infuse_by` (2026-08-14T12:00:01Z = collected_at + `VIABILITY_HOURS[PBSC]` 72h + 1s).
- RBAC section pins auth-ladder ordering twice: priority 2 answers before priorities 5/6 (unauthorized probes carrying non-existent ids still get 403, never 404), and priorities 7/8/9 answer before the state rules at 11+ (peer probes target resources that are also in the wrong state and still get the scope error).
- Both `concurrency_rules` get an OCC instance; the patient one shows priority 34 beating the conditioning state rules (412, not 409) and that a rejected write never bumps `version`.
- `selector_policy` is the one declared complexity layer with no row in `claim-extraction-guide.md`; rather than invent a `claim_type`, it is asserted through the §1.3 candidate-selector instances in the `calculations` section, and that choice is documented in a comment in the file.

## Step 3: Copy shared files — 2026-09-03T09:26:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2535_marrow_donor_registry_search_workup/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T09:44:00.000Z

Done. PRD generated and fully verified.

## Output
`workspace/PRD.md` — **431 lines**, 28 headings, built via one small `Write` plus 11 incremental `cat >> ... <<'PRDEOF'` heredoc appends (no single giant write, so no 64k-cap truncation).

## Section list
- `# Marrow Donor Registry Search & Workup API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and RBAC · 2.2 API Response Structure · 2.3 Pagination and List Ordering · 2.4 The Logical Clock · 2.5 Common Record Properties · 2.6 Numeric Precision: Scores, Cents, Dates and Intervals · 2.7 Version Guards on Case-Level Writes · 2.8 Path and Payload Reference Resolution · 2.9 The Order in Which Rules Are Evaluated · 2.10 Derived Counters and the Reversibility of Cascades · 2.11 Two-Physician Donor Safety and Registry Scope
- `## 3. Business Logic & Workflows` — 3.1 Standing Up the Programme · 3.2 The Donor Pool · 3.3 The Patient Case and the Preliminary Registry Search · 3.4 Confirmatory Typing · 3.5 Health Screening, Deferral and the Backup Promotion Cascade · 3.6 The Donor Workup · 3.7 Booking the Collection, Harvesting the Product and Courier Transport · 3.8 The Conditioning Timeline and Its Dependencies · 3.9 Follow-Up, Adverse Events and Cost Reimbursement
- `## 4. Endpoint Definitions` (47-row table)
- `## 5. Error Code Catalogue` (66-row table)

## Verified coverage
- **Endpoints: 47/47**, role lists match the scaffold on all 47 (0 mismatches).
- **Errors: 66/66**, all 66 HTTP status codes match the scaffold (0 mismatches).
- **Contract 1 (field-name coverage): PASS** — 127/127 entity field names and 66/66 endpoint input identifiers appear verbatim in backticks.
- **Contract 2 (rule coverage): PASS** — all states of all 11 state machines in backticks; all 55 validation error ids named in prose; 63 transitions, 9 calculations, both OCC rules and all cascades narrated.
- **Contract 3 (§3 path purity): PASS** — 956 backtick tokens in §3; 0 containing a slash, 0 bare HTTP methods.

## Fixes applied during verification
- `item_type` (ClearanceItem) added to §3.6 (only missing field name).
- Closed 3 Contract-2 gaps: workup-open search-terminality precondition; exact enumeration of 6 registry-scope + 5 centre-scope writes; §3.8 abort cascade cancelling still-`REQUESTED` typing requests.
- Six constants existed only as English words (48h international grace, 24h priority reduction, 90-day clearance-fail deferral, 90-min turnaround buffer, 300/240-min durations, 72/48h viability) plus two rates (0.40, 0.08) — digit forms added alongside the prose.

## Constraints honored
Neither design index was opened, grepped, or referenced. No sibling task directory was read. PRD ends at §5's final table row.

**Orchestrator truncation check:** `wc -c` = 110477 bytes; final line is `| \`ERR_PATIENT_BUDGET_EXCEEDED\` | 402 |`, a complete final row of the §5 table — a real section boundary, not mid-sentence. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T10:31:00.000Z

Test generation for task 2535 is complete and verified.

## Stage 1 — `test_helpers/` (2,427 lines, 9 files)

| file | lines |
|---|---|
| `__init__.py` | 53 |
| `api_client.py` | 285 |
| `api_errors.py` | 146 |
| `assertions.py` | 345 |
| `constants.py` | 113 |
| `factories.py` | 234 |
| `fixtures.py` | 712 |
| `test_users.py` | 77 |
| `types.py` | 462 |

`api_client.py` covers all 47 endpoints under the `/registry` prefix; `api_errors.py` registers all 66 error IDs with their HTTP statuses so `validate_error` cross-checks status automatically; `fixtures.py` exposes `setup_pipeline(stage=...)` walking the only PRD-legal ordering across 14 stages on a canonical timeline (clearance 2026-09-11, IDM expiry 2026-10-11, conditioning start 2026-10-05, legal collection 2026-10-11..13, delivery 2026-10-12).

## Stage 2 — `test_suite/` (8,920 lines, 17 test files + conftest)

122 test functions -> **168 collected pytest items**. Per-file counts: 6/6/5/4/5/4/7/5/5/14/11/5/4/7/26/4/4.

## Verification (all clean)

- `py_compile` passes on every file in both directories; `pytest --collect-only` collects 168 items with no import or fixture errors.
- **Design-tag audit**: every one of the 122 tests carries exactly one `Design:` line, it is the last docstring line, and every tag resolves to a real instance. Zero untagged, dual-tagged, or dangling tags.
- **Coverage: 69/69 instances translated, 0 skipped.** Queue A: all 19 difficulty instances, each with >=2 tests. Queue B: all 50 non-stub corner instances, each with >=1 test.
- **All 23 `excluded_because:` stubs verified**: every `difficulty_instance` cross-reference resolves to a real `name:`; no tests or placeholders emitted for them.
- **Citations: 581 quoted PRD sentences checked, 0 misses** — every one survives a whitespace-normalised literal match against `workspace/PRD.md`.
- No `pytest.mark.skip` / `skipif` / `xfail` / `TODO` anywhere. `workspace/implementation/` was never read by any agent.

## Design-index bugs found (yaml literals that contradict the PRD; the PRD value was asserted instead)

1. **`entities/donor_creation_rejects_out_of_range_numbers_and_unknown_enum_values`** — yaml rejects ages 17 and 61; PRD §3.2 says verbatim that ages 17–75 are accepted. Re-based to reject 16/76, accept 17/75.
2. **`state_machines/opening_a_workup_case_fires_its_three_declared_side_effects`** — yaml expects `planned_window_days: null`; PRD §3.6 says it "starts at 6".
3. **`validations/the_deadline_guard_rejects_a_late_response_without_any_sweep`** — yaml asserts candidate status `EXCLUDED_LOW_MATCH`, not one of the ten legal states; PRD says `EXCLUDED`.
4. **`validations/booking_checks_run_as_a_ladder...`** — yaml asserts `clearance_status "INCOMPLETE"`; PRD §3.6 opens a case at `PENDING`.
5. **`compensating_invariant/claim_void_restores_patient_committed_cost...`** — yaml expects the failed candidate at `EXCLUDED`; PRD §3.6 moves it `WORKUP_OPEN -> DEFERRED`.
6. **Three instances assert the search stays `PRIMARY_ENGAGED` after a primary DEFER**; PRD §3.5 moves it to `BACKUP_REQUIRED`.
7. **`non_linear_state_machine/workup_case_...dimensions_advance_independently`** — recipe unsatisfiable as written (replacement booking 2026-10-12 + canonical 2026-09-11 clearance trips `ERR_IDM_RESULT_EXPIRED`). Test uses a local clearance date of 2026-09-13.
8. Also: logistics `SLOT_HELD` -> should be `BOOKED`; clearance item `INFORMED_CONSENT` -> should be `CONSENT`; one international-total fee literal was 220700 where the pinned discount-then-fee order gives 209665.

## Sub-assertions deliberately dropped (instances still translated)

Mostly `branch-asymmetry` and `computed-field` silences: `confirmed_match_grade` when `donor_available_flag` is false; `cancelled_after_confirmation` on the conditioning-abort path; `released_at` on cascade-released windows; `void_reason`/`abort_reason` string values (asserted non-null); `backup_candidate_count` while a backup sits in `TYPING_EXPIRED`; HLA allele ordering within a locus. One whole branch dropped under `applies_to-scope`: PRD §3.8's "Only the coordinator who owns the patient may act, whichever of the two roles is calling" contradicts §2.9 rung 7 and §2.1, so the conditioning branch of `shared_operations_accept_either_declared_role` is not uniquely derivable. Instant-valued fields compared as parsed datetimes rather than ISO strings, since §2.5 mandates three fractional digits but does not pin rendering.

**Orchestrator note on isolation.** Steps 5 and 6 were launched sequentially rather than in one message, so `test_suite/` already existed on disk when Step 6 started. To restore the physical isolation the skill's concurrent launch is designed to give, the orchestrator moved `test_helpers/` and `test_suite/` out of the task tree (to `/tmp/task2535_tests_hold/`) for the entire duration of Step 6 and moved them back immediately afterwards. Step 6's implementation generator therefore could not read any test file even had it tried; the guarantee is equivalent to the concurrent launch.

## Step 6: Generate implementation — 2026-09-03T10:57:00.000Z

The implementation is complete.

## Files (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 78 | factory, blueprint registration, `before_request` -> `store.begin_request()`, `ApiError`/400/404/405/500 handlers, `PORT` launch |
| `store.py` | 147 | in-memory `db` (14 dicts), logical UTC clock (`2026-08-01T00:00:00Z`), `new_row`/`touch`/version de-dup, ISO parsing/formatting |
| `errors.py` | 91 | 66-entry `ERROR_HTTP` catalogue + `ApiError` |
| `envelope.py` | 85 | envelope, `req_<20>` ids, list meta, pagination reader |
| `auth.py` | 55 | `X-User-ID`/`X-User-Role`, 5 roles |
| `validate.py` | 280 | schema helpers, `Decimal` body parse, HLA typing validators |
| `calc.py` | 332 | pinned constants, scoring, deadlines, interval maths, 6 re-derived counters, `claim_amounts` |
| `serializers.py` | 274 | 14 entity serializers |
| `cascades.py` | 382 | promotion/stall, window release, clearance-fail and conditioning-abort cascades |
| `claims.py` | 74 | PROVISIONAL/FINAL variants |
| `guards.py` | 30 | `find`, `render_list`, query arg |
| `routes_registry.py` | 116 | 6 endpoints (incl. `/_clock/set_current_utc`) |
| `routes_patient.py` | 352 | 7 endpoints |
| `routes_donor.py` | 248 | 9 endpoints |
| `routes_candidate.py` | 340 | 8 endpoints |
| `routes_workup.py` | 122 | 5 endpoints |
| `routes_booking.py` | 365 | 12 endpoints |
| `start.sh` | 10 | guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

3382 lines total. All modules `py_compile` clean; no `__pycache__` left behind.

## Verification
- **Endpoints: 47** — enumerated from Flask's `url_map` and matched 1:1 against the PRD §4 table (47 rows).
- **Error ids: 66** — catalogue is exactly the PRD's 66 distinct ids, every HTTP status matches the §5 table, and a regex sweep confirms all 66 are raised in code (0 unwired, 0 extras).
- **No persistence / no seeding** — no file I/O, sqlite, pickle or `/tmp` anywhere; all 14 collections empty at import, clock reads `2026-08-01T00:00:00Z`.

## Smoke test (`PORT=18535 bash start.sh`)
Booted in ~1s. Beyond the required create+read (`POST /registry/registries` -> 201, `GET .../{id}` -> 200, envelope exactly `meta{api_request_id, api_request_timestamp}` / `response_type` / `data` with `id, created_at, updated_at, version` + re-derived `donor_count`), two full end-to-end scenarios ran:

1. **Happy path (39 calls, 0 unexpected statuses):** registry -> centre -> patient -> donor -> search (prelim 100.0, rank 100.0, PRIMARY) -> typing request (deadline 2026-08-04) -> response (10/10) -> screening PASS -> workup case + 3 clearance items in pinned order -> 3 PASS results -> clearance `CLEARED` -> SoD self-approval refused 403, second physician sets PBSC (`planned_window_days` 6) -> conditioning SCHEDULE -> out-of-window booking refused `ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW` 422, in-window booking 201 (`end_at` +300 min, case -> `BOOKED`, version bumped) -> confirm creates the 2026-08-03..08-08 PBSC window (`day_count` 6, `blocked_day_count` 6, `committed_slot_minutes` 300) -> START -> shipment `ADEQUATE`, `must_infuse_by` +72h -> DEPARTED, duplicate DEPARTED refused 409, DELIVERED -> case `DELIVERED` -> INFUSE -> case `COMPLETED`, search `FULFILLED` -> claim finalize: lines `[34500, 78000, 52500, 1450000, 265000, 192000, 0]`, **total 2,072,000** — the PRD's pinned domestic-PBSC fixture.
2. **Cascade path:** MARROW consent gate (`ERR_DONOR_METHOD_NOT_CONSENTED`, 8 window days), stale version 412, centre scope 403, supersede (`SUPERSEDED_BY_NEW_BOOKING`, minutes back to 240), confirm-then-cancel (`cancelled_after_confirmation` true, blocked days 8 -> 0, logistics `BOOKED` -> `METHOD_SET`, minutes -> 0), re-cancel refused, reschedule cancels the now-out-of-window booking with `CONDITIONING_RESCHEDULED`, and ABORT -> case `ABORTED`/`CONDITIONING_ABORTED`, search `STALLED`, claim `VOID`, `committed_cost_cents` back to exactly 0.

The only two "FAIL" lines in that run were the probe script's own wrong expectations (409 vs. the catalogue's 422/412); the server returned the catalogued statuses. Server killed afterwards; port free.

Two documented judgement calls: rung-7 ownership is enforced only when the acting role is `TransplantCoordinator` (scaffold wording over PRD §3.8's looser phrasing), and the `WORKUP_ACTIVE`-search precondition applies only to `SCHEDULE` from `NOT_SCHEDULED`, with reschedule instead blocked by any `COMPLETED` booking.

## Step 7: Run tests and iterate — 2026-09-03T11:21:00.000Z

All 8 parallel rounds green: **168/168 passed in every round**.

## Summary

**Iterations run:** 2 (sweep -> 5 consistent failures in all 8 rounds -> fixes -> sweep -> 8/8 clean).

No flakiness was observed: the 5 failures were identical and deterministic in all 8 rounds of iteration 1, and iteration 2 was uniformly green.

**Tests deleted:** none. Every failing test's rule was verbatim in `workspace/PRD.md`; all 5 failures were test-artifact bugs (STEP 1c / STEP 2), not PRD silences.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_same_instant(actual, expected, label)`. PRD §2.4 pins that instant-valued fields "are compared exactly, to the second" but pins a three-fractional-digit rendering only for `created_at` / `updated_at` / `api_request_timestamp` (§2.2, §2.5). Raw-string equality on instant fields therefore asserted an unpinned serialization; the helper keeps the PRD-covered instant equality and drops the uncovered rendering assertion (STEP 1c partial coverage).

**Fixes applied to `test_suite/`:**
- `test_08_slot_and_calendar_overlap.py` — 3 raw-string instant comparisons (`booking_a["end_at"]`, `booking_b["start_at"]`, `booking_b["end_at"]`) converted to `A.assert_same_instant`; added `assertions as A` import.
- `test_04_deep_cascades.py` — `failed["resulted_at"]` string comparison converted to `A.assert_same_instant`; added `assertions as A` import.
- `test_09_compensating_counters.py` — `rebooked["start_at"]` string comparison converted to `A.assert_same_instant`.
- `test_17_version_guards_counters_and_visibility.py::test_booking_create_rejects_a_stale_workup_case_version` — real fixture bug, not a rendering issue. The test's replacement booking used `TIMELINE["WINDOW_MID_DATE"]` = `2026-10-12`, but the canonical timeline's `IDM_PANEL` `expires_at` is `2026-10-11T08:00:00Z`, so the PRD-faithful implementation correctly answered `ERR_IDM_RESULT_EXPIRED` (422) per §3.7 ("the booking's `collection_date` must fall on or before the UTC calendar date of the `IDM_PANEL` clearance item's `expires_at`"). Retargeted the replacement slot to `2026-10-11T14:30:00Z` — same legal IDM day, and exactly the buffered-interval end instant of the first 08:00–13:00 slot, which §3.7 states is admitted at capacity 1. The version-guard assertion the test exists for is unchanged (the stale attempt still resolves at the `ERR_STALE_WORKUP_VERSION` rung, which §3.7 places before the IDM check).

**Fixes applied to `implementation/`:** none. No implementation defect was found; the `.000Z` rendering and the IDM-expiry refusal were both PRD-correct behaviour.

### Orchestrator verification of the Step 7 claim

The Step 7 subagent exited claiming a clean 8-round sweep but left **no `results.*.json` and no `sweep.log` on disk** — the known "claimed-clean-but-unproven sweep" failure mode. The orchestrator therefore re-ran the full 8-round sweep itself, under `setsid nohup` per the reaping guard, and parsed every results file:

```
results.1.json .. results.8.json : 168/168 passed, failed=0, errors=0, skipped=0  (all eight)
Duration ~295s per round; grep -c 'Terminated' sweep.log = 0 (no reaping)
```

Step 7's PASS is confirmed by first-hand evidence. Because Step 7 applied fixes (4 `test_suite/` files, 1 `test_helpers/` addition) it did NOT exit on the first sweep, so Step 8's skip condition does not apply and Step 8 runs.

## Step 8: Finalize PRD — 2026-09-03T11:26:00.000Z

Done. One PRD edit, traceable to the `assert_same_instant` helper introduced in Step 7.

## Counts
- `PRD.md`: 431 lines — `PRD_FINALIZED.md`: 431 lines — **0.00 % line delta** (one line, §2.4, revised in place; +~590 chars, ~ +0.5 % by bytes).

## Change
- **§2.4 (The Logical Clock, instant/date granularity paragraph)** — *insert* — after the existing "…are compared exactly, to the second." sentence, added that **every** instant-valued field a response payload carries (the listed ones, plus `idm_resulted_at`, `last_followup_at`, and the clock capability's `current_utc` / `previous_utc`) is rendered, when non-null, as an ISO 8601 UTC timestamp with exactly three fractional digits and a trailing `Z`, regardless of the precision of the stored instant or the client-supplied string — with the `2026-10-11T14:30:00Z` -> `2026-10-11T14:30:00.000Z` example — `implementation/store.py:136-141` (`fmt_instant`), applied at `serializers.py:22-23,86,108,139-146,161,175-177,189-194,212,221-229,239-244,271`, `envelope.py:26`, `routes_registry.py:114-115`.

## Pre-edit search log
Edit 1 — instant-field serialization
- **(a) Subject:** the wire rendering of instant-valued fields (as distinct from the comparison semantics PRD already pins).
- **(b) Impl paths enumerated / read:** `store.py` `fmt_instant` (the single renderer) and `fmt_date`; every serializer in `serializers.py` — confirmed all 24 instant emissions route through `fmt_instant`, none through `isoformat()`; `envelope.py:base_meta` (`api_request_timestamp`); `routes_registry.py:105-115` (`POST /_clock/set_current_utc` -> `current_utc` / `previous_utc`); repo-wide grep for `isoformat|fmt_instant` confirmed `fmt_date` is the only other formatter and serves only the five date-valued fields §2.4 already pins; `routes_booking.py:62,124` confirmed `start_at` is stored as a parsed `datetime` (client string not echoed), which is why the raw-string assertions failed; claim `line_items` carry no instants.
- **(c) Wording adjustments made:** (1) scoped the claim to fields "that a response payload carries" and added "whenever it carries a value at all", so the many nullable instant fields PRD elsewhere pins as `null` are not mis-described as timestamps; (2) explicitly named `idm_resulted_at`, `last_followup_at`, `current_utc`, `previous_utc` — instant fields the impl renders identically but which §2.4's list omits; (3) framed it as rendering only, deliberately not touching the existing exact-to-the-second comparison rule, since the impl compares full `datetime` values while rendering truncates to milliseconds; (4) avoided any claim about rounding vs. truncation of sub-millisecond input.

## Step 7 items that produced no PRD edit
- The four `test_suite/` conversions are the same silence as Edit 1 — covered, no further patch.
- `test_17::test_booking_create_rejects_a_stale_workup_case_version` was a pure fixture bug. Impl verified against PRD verbatim: `routes_booking.py:76-89` checks `ERR_STALE_WORKUP_VERSION` before the `IDM_PANEL` expiry-date comparison, and the expiry test is `collection_date > expires_at.date()` — exactly §2.9's ladder and §3.7's wording. No PRD silence or mismatch, so no edit.
- No `implementation/` fixes and no test deletions in Step 7, so no other candidate sites exist.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 86, §2.4); 431 lines both, 110477 -> 111078 bytes. Minimal patch confirmed.

## Step 9: Complete PRD — 2026-09-03T11:45:00.000Z

Run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` (seeded by the orchestrator as `cp PRD_FINALIZED.md PRD_COMPLETED.md`), so no one agent had to scan all 3382 implementation lines at once. Each pass edited the file in place with `Edit` only.

### Size progression
| stage | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` (baseline) | 431 | 111,078 |
| after PASS A (app/store/errors/envelope/auth/validate/guards/serializers) | 432 | 117,252 |
| after PASS B (calc/cascades/claims/routes_registry/routes_patient/routes_donor) | 432 | 121,351 |
| after PASS C (routes_candidate/routes_workup/routes_booking) | 432 | 124,465 |

Cumulative: **+1 line, +13,387 chars** over `PRD_FINALIZED.md`; 45 lines changed. **Total: 37 ambiguity-pins, 8 mismatch-revisions.**

### PASS A — 11 ambiguity-pins, 2 mismatch-revisions
- §2.1 — revise — ambiguity — blank/whitespace-only `X-User-ID`/`X-User-Role` is also `ERR_UNAUTHENTICATED`; role compared case-sensitively and untrimmed while `X-User-ID` is stripped — `auth.py:47-52`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A`–`Z`/`0`–`9` (24 total) — `envelope.py:11,20`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the §2.4 logical clock, not host wall time — `envelope.py:26`
- §2.2 — revise — **mismatch** — error envelope covers 4xx **and 5xx**, not 4xx only — `app.py:63-68`
- §2.2 — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST`/404, undefined method -> 405, unhandled fault -> 500, trailing-slash equivalence, message wording never load-bearing — `app.py:33,50-68`
- §2.3 — insert — ambiguity — empty-valued `limit`/`offset` rejected; only a minus-prefixed digit run parses; `offset` past `total_count` yields an empty page with `has_more` false — `envelope.py:59-85,55`
- §2.3 — insert — ambiguity — all three orderings settle residual ties by write order; filter params are exact unvalidated string matches, so an unknown value yields an empty page not an error — `store.py:105-107`, `guards.py:21-26`, `routes_donor.py:31-37`
- §2.4 — insert — ambiguity — inbound instants accepted with `Z`/`z`, explicit offset, or no zone marker (read as UTC) and normalised; inbound dates exactly 10 chars — `store.py:110-133`
- §2.5 — insert — ambiguity — `version` increments once per row per **request**, not per field write — `store.py:84-102`
- §2.6 — insert — **mismatch** — a stated decimal-place count is a **maximum on the literal as written**, not exactness; ints accepted for decimals; booleans never numbers; decimals render as bare JSON numbers — `validate.py:119-142`, `serializers.py:11-16`
- §2.9 rung 3 — insert — ambiguity — absent/empty body read as `{}`; non-object body is itself `ERR_INVALID_REQUEST`; `Content-Type` never inspected; explicit `null` counts as absent; enum arrays reject repeats; HLA strings trimmed, ordinary strings verbatim — `validate.py:25-42,204-252,57-66`
- §3.2 — revise — ambiguity — allele-level = exactly two colon-separated non-empty parts; antigen-level = one with no colon; `07:02:01` is neither — `validate.py:17-18,244-249`
- §3.4 — revise — **mismatch** — a CT response string with **more than one** colon also fails `ERR_CT_TYPING_NOT_ALLELE_LEVEL` — `validate.py:274-275`
- §4 preamble — revise — **mismatch** — envelope claim narrowed to every response *carrying a body* (the 204 release has none) — `routes_donor.py:167`, `envelope.py:30-36`
- Found already fully pinned: `errors.py` (all 66 id->status pairs match §5 exactly, same order), `app.py` wiring, `serializers.py` field names (all 14 serializers' fields already in prose; field order deliberately not pinned since JSON object order is not semantically observable), `guards.py`.

### PASS B — 13 ambiguity-pins, 3 mismatch-revisions
- §3.1 — insert — ambiguity — `is_domestic` required boolean, no default, immutable on update — `routes_registry.py:36,65-68`
- §3.1 — insert — ambiguity — a PATCH supplying none of the four optional fields still succeeds and still advances `version` — `routes_registry.py:61-79`
- §3.2 — insert — ambiguity — the `DEFERRAL` release test reads the donor's `deferral_until`, not the window's `date_to`, so a permanently-deferred donor's window can never be hand-released — `routes_donor.py:152-155`
- §3.3 — insert — ambiguity — the materialisation tie beyond donor `created_at` is settled by donor write order — `routes_patient.py:150-151`
- §3.3 — insert — ambiguity — a `NO_MATCH_FOUND` search is created directly in that state: `version` 1, `updated_at` == `created_at` — `routes_patient.py:179-180`
- §3.4 — insert — ambiguity — deadline arithmetic is not floored at `requested_at`; a short window plus `priority_flag` yields a past deadline — `calc.py:197-203`
- §3.4 — insert — ambiguity — every sweep bumps the search `version`, returns the search row, and is never refused for the search's own status — `routes_patient.py:186-215`
- §3.5 — insert — ambiguity — cross-search exclusions run no promotion cascade and leave other searches' `status` untouched even where the excluded candidate was their `PRIMARY` — `cascades.py:227-239`
- §3.5 — revise — ambiguity — with no promotable backup the search *still* moves to `BACKUP_REQUIRED`; only the sweep or the conditioning abort writes `STALLED` — `cascades.py:191-199,213-224`
- §3.6 — insert — ambiguity — `abort_reason` and the claim's `void_reason` both carry the fixed token `CLEARANCE_FAILED` — `cascades.py:303-323`
- §3.6 — insert — ambiguity — the 90-day deferral reaches only an `AVAILABLE` donor; an already-deferred/withdrawn donor is untouched and gets no window — `cascades.py:314-317`
- §3.8 — revise — **mismatch** — ownership binds only the `TransplantCoordinator`, never the `MedicalDirector` — `routes_patient.py:242`
- §3.8 — insert — ambiguity — `expected_patient_version` is checked as a non-negative integer at the schema rung (negative -> `ERR_INVALID_REQUEST`, not 412); superfluous fields accepted and ignored — `routes_patient.py:229-239`
- §3.8 — revise — **mismatch** — logistics reverts `BOOKED -> METHOD_SET` only once no `HELD`/`CONFIRMED` booking is left on the case, not per cancelled booking — `routes_patient.py:336`, `cascades.py:284-291`
- §3.8 — revise — **mismatch/ambiguity** — `void_reason` is the fixed `CONDITIONING_ABORTED` token (never the client reason); `logistics_status` is not reverted; with no `OPEN` case the cascade acts on the patient's most recently created non-terminal search — `cascades.py:339-382`
- §3.9 — insert — ambiguity — the §2.11 registry-scope check binds only the liaison, not a `MedicalDirector` — `routes_donor.py:195`
- §3.9 — insert — ambiguity — the move to `PERMANENTLY_DEFERRED` on adverse event is unconditional, including from `PERMANENTLY_DEFERRED`/`WITHDRAWN` — `routes_donor.py:226-230`
- §3.9 — insert — ambiguity — `volume_discount_pct` is the number zero (not null) when no tier is earned — `calc.py:308-314`
- Found already fully pinned: `claims.py` (both variants' differing inputs pinned verbatim in §3.9) and essentially all of `calc.py` (every constant, the 9.6 divisor, 3.5 ambiguity penalty, three-branch logistics factor, 0.55/0.25/0.20 blend, 48/24 deadline adjustments, 6–8 day window, method offsets/durations/viability, 90-minute buffer, 90/30-day spans, all seven fees, both discount tiers, all six derived counters); `routes_registry.py` clock capability and centre endpoints.

### PASS C — 13 ambiguity-pins, 3 mismatch-revisions
- §2.7 — insert — ambiguity — `expected_workup_case_version` read at the schema rung as a non-negative integer, so negative/non-integer is `ERR_INVALID_REQUEST` not a version mismatch — `routes_booking.py:64`
- §3.4 — insert — ambiguity — the typing-response call answers with the updated **typing request** row on both availability branches — `routes_candidate.py:190,208`
- §3.4 — insert — ambiguity — on the sub-nine-match path `confirmed_match_grade`/`reported_match_grade` are stored with `confirmed_score`; on the unavailable path all three stay null while the reported typing is still stored — `routes_candidate.py:174-206`
- §3.5 — insert — ambiguity — `questionnaire_flags` must be an object when supplied and is then discarded; the screening call answers with the updated **candidate** row — `routes_candidate.py:219,272`
- §3.5 — insert — ambiguity — the `DEFER` donor move reaches only an `AVAILABLE` donor; the candidate still moves to `DEFERRED` and the cascade still runs — `routes_candidate.py:256-259`
- §3.5 — revise — **mismatch** — the `FAIL` donor move to `PERMANENTLY_DEFERRED` is unconditional, clears `deferral_until`, leaves an `ACTIVE` `DEFERRAL` window `ACTIVE`; candidate reaches `EXCLUDED` from `TYPING_RESPONDED` *or* `DEFERRED` — `routes_candidate.py:261-268`
- §3.6 — insert — ambiguity — on workup open the search reaches `WORKUP_ACTIVE` from any non-terminal status; one already `WORKUP_ACTIVE` is untouched (no `version` bump) — `routes_candidate.py:336-338`
- §3.6 — insert — ambiguity — clearance-result `note` capped at 400 chars — `routes_workup.py:52`
- §3.6 — insert — ambiguity — the clearance-result call answers with the updated **clearance item** row however deep the cascade — `routes_workup.py:90`
- §3.6 — insert — ambiguity — `rationale` is a non-empty string of any length, validated then discarded — `routes_workup.py:98`
- §3.7 — insert — ambiguity — a booking `start_at` with non-zero seconds is accepted exactly as supplied, never rounded or refused — `routes_booking.py:63`
- §3.7 — insert — ambiguity — the centre-capacity count runs **before** the supersede step and is not scoped to other cases, so a re-booking counts its own case's still-`HELD` overlapping slot — `routes_booking.py:104-120`
- §3.7 — insert — **mismatch** — booking confirm never parses its body, so a non-JSON payload is ignored rather than refused (narrow exception to §2.9 rung 3) — `routes_booking.py:142-149`
- §3.7 — insert — ambiguity — cancel takes a non-empty `reason` of any length; centre scope binds only `CollectionCenterOps`, so a `MedicalDirector` may cancel any centre's booking — `routes_booking.py:174-180`
- §3.7 — insert — ambiguity — transit-event `note` capped at 400 chars; centre scope binds only `CollectionCenterOps`, a `RegistryOperations` filer being unscoped — `routes_booking.py:270-276`
- §3.9 — insert — **mismatch** — claim finalize never parses its body, so a non-JSON payload is ignored rather than refused — `routes_booking.py:344-347`
- Already uniquely pinned in this partition: all 15 read/list endpoints (role sets vs §4, filter field lists, `rank_position`/`start_at`/`created_at` orderings, pagination-read-before-path-id), the whole booking-creation validation ladder and its precedence, IDM-validity and conditioning-window rules, the buffered-overlap formula, the supersede reason token, the shipment derivations (`must_infuse_by`, `dose_adequacy`, viability branch on `DELIVERED`), the clearance ordering ladder and the `IDM_PANEL` 30-day expiry, the collection-method gates and `planned_window_days` 6/8, and the claim finalizability rule.

### Document sanity checks (PASS C, re-verified by the orchestrator)
1. §4 endpoint table: **47 data rows**
2. §5 error table: **66 data rows**
3. Headings: 28, all intact and in order — H1, §1, §2 with §2.1–§2.11, §3 with §3.1–§3.9, §4, §5; no duplicates, no gaps
4. Ends at a real boundary: final line is the §5 row `` | `ERR_PATIENT_BUDGET_EXCEEDED` | 402 | ``, not mid-sentence

### Orchestrator verification
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs** (the byte-identical "scan never ran" failure mode did not occur); 45 changed lines.
- No file under `test_suite/`, `test_helpers/` or `workspace/implementation/` was modified after the 11:21 verification sweep, so the independently confirmed 8x 168/168 green result still describes the delivered artifacts. Step 9 touched documentation only.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written.
