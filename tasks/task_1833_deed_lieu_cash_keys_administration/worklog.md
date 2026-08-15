# Worklog — task_1833_deed_lieu_cash_keys_administration

## Step 1: Create Task Directory — 2026-08-14T19:26:00.000Z

Pre-created by pipeline launcher: tasks/task_1833_deed_lieu_cash_keys_administration/ and workspace/ verified to exist; skipped per command args.

## Step 3: Copy Shared Files — 2026-08-14T19:27:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1833_deed_lieu_cash_keys_administration/workspace/INSTRUCTION.md (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T20:18:00.000Z

Done. The scaffold for task 1833 was generated purely from the scenario description plus the skill specification, and `scaffold_lint.py` reports a clean verdict: all 1,420 §1.8/§1.9 calls conform to §1.5 and every §1.1 FK has reverse-reachability.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys inside)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**§1.1–§1.7 surface:**
- **Entities: 15** — Loan, Borrower, Property, WorkoutCase, MarketingListing, ListingSuspension, TitleCommitment, JuniorLien, SettlementAgreement, InspectionAppointment, InspectionReport, Disbursement, DeficiencyWaiver, DeedRecording, EvictionCase (flat topology, FK-linked)
- **State machines: 12** (71 transitions) — including a branching/cyclic WorkoutCase (program-type fork DIL→RECORDING_PENDING vs CFK→COMPLETED, holdover escalation arc, eviction-dismiss cycle back to TERMS_NEGOTIATION), a cyclic negotiation loop on SettlementAgreement (OFFERED↔COUNTERED with round cap), a cure-and-reinspect loop, and bubble-up TitleCommitment CLEARED logic with a CLEARED→RECEIVED reopen
- **Endpoints: 76** (75 business + `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- **Error catalog: 54** codes across a 27-row priority-ordered validation ladder (auth → authz/ownership → existence → state → SoD safety → constraint → temporal → referential → fiscal)
- **Roles: 8** with segregation-of-duties (disbursement approve ≠ request, release ≠ approve, tracked by X-User-ID), entity-backed Borrower ownership, inspector-identity binding
- **Concurrency: 2** true-race OCC rules (case version on agreement create, title-commitment version on lien release), each with its own 412 error

**§1.8 difficulty design: 23 non-stub instances** (≥2 per rule; combinatorial_formula, non_linear_state_machine, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency each carry 3). All formula-derived asserts are pre-computed literals (verified by executing the formulas in Python — e.g., provisional 550000 → final 475002, per-item rounding 59998 vs 59997, projected waiver 2601928 vs final 2615080, merged-interval creditable days 31 vs naive 32/67).

**§1.9 corner design: 77 instances — 69 non-stub + 8 `excluded_because` stubs** across all nine taxonomy sections (entities 8, state machines 11+4 workflow-completion, calculations 4, validations 16, endpoints 3, errors 2 + 11 not-found sweep, RBAC 5, cross-cutting layers 4, consistency 1).

Post-lint verification also confirmed: instance-name uniqueness across both design files, full `${var}` placeholder closure, all `grounds:` refs resolve into §1.1–§1.7, all stub citations reference real §1.8 instances, no forbidden race vocabulary, enum closure, and every error code referenced by at least one validation/transition/concurrency rule. (The pre-existing `worklog.md`/`workspace/` in the task directory were left untouched.)

## Step 4: Generate PRD — 2026-08-14T20:45:00.000Z

All checks pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/workspace/PRD.md` — 354 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Monetary Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Hierarchical Consistency and Cascading State Propagation · 2.9 Nested Resource Retrieval and Identifier Resolution · 2.10 Validation Order and Error Priority · 2.11 Segregation of Duties in Fund Disbursement
- §3 Business Logic (timeline grouping, 9 subsections): 3.1 Boarding Reference Data · 3.2 Case Intake, Eligibility, Withdrawal · 3.3 Marketing Period & Creditable Days · 3.4 Title Clearance · 3.5 Settlement Agreement Negotiation · 3.6 Handover Inspection & Condition Assessment · 3.7 Relocation Assistance Disbursement · 3.8 Deficiency Waiver, Deed Recording & Completion · 3.9 Holdover Escalation & Eviction Docket
- §4 Endpoint Definitions (76 rows, 4 columns, all scaffold paths present)
- §5 Error Code Catalogue (54 rows, 2 columns)

**Zero-Silence self-audit (all three hard contracts PASS):**
- **Contract 1 (fields):** 98 required identifiers (all entity fields, endpoint inputs incl. `to_iso8601`/`decision`/`notes`/`offer_valid_days`/`proposed_vacate_date`/`expected_case_version`/`expected_title_commitment_version`/`lien_id`, query params, `item_code`/`severity`, common fields) — 0 missing; all 54 error IDs and all 8 role names appear in backticks. One initial gap (`title_commitment_id`) was found by audit and repaired.
- **Contract 2 (rules):** every state machine's transitions/preconditions/side-effects expressed (incl. the withdraw cascade, eviction-dismissal 2x2 matrix, recording-confirm 3-hop cascade, report-submit 2-hop fork, release zero-remaining DIL/CFK fork); all 6 calculations rendered as pinned-order natural-language prose with constants embedded (tiers, 0.8/0.5 multipliers, hardship bonuses, 150,000 floor before 1,200,000 cap, per-item rounding with the 59,998-vs-59,997 example, clamp→sort→merge→subtract interval union, projected/final waiver variants, 15,000-cents/day penalty with vacate+3/vacate+4 boundary); all 25 validations matched to error IDs with the pinned orderings stated (conflict-before-notice, expiry-before-liens, remaining-ceiling-last, existence-before-creditable-days, shared priority-8 disjointness); both OCC rules named with endpoint + `expected_*_version` field + exact error ID + HTTP 412.
- **Contract 3 (§3 path purity):** 584 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos.

One scaffold ambiguity resolved on the record: the clock-set endpoint description vs. the `OFFERED→EXPIRED` state-machine note ("the clock-set endpoint does NOT sweep") conflict; the PRD follows the state machine — expiry is lazy, the clock performs no eager sweep — while preserving the endpoint's observable outcome (agreements do flip to `EXPIRED` on next read/action). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directory was read.

## Step 6: Generate Implementation — 2026-08-14T20:50:00.000Z

76 application routes (77 minus Flask's built-in `/static/<path:filename>`), covering all 73 endpoints declared in the scaffold (a few declared paths share rules). Everything is implemented and verified.

## Summary

**Files generated** in `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/workspace/implementation/`:

- `start.sh` — executable launcher; guards the pip install with `python3 -c "import flask"` so per-test reboots skip reinstall; `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` — `flask>=3.0.0`.
- `app.py` — Flask application with all routes, auth/RBAC, validation ladder, and cascades.
- `db.py` — in-memory stores (15 dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), UUID/timestamp/version helpers. No seeding — store starts empty on every boot.
- `errors.py` — `ApiError` plus the full 53-entry error catalog with HTTP statuses.
- `response.py` — envelope helpers producing `{meta:{api_request_id, api_request_timestamp}, response_type, data}` with `limit/offset/total_count/has_more` in meta for lists; error body uses `error_id`/`message`.
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 8-role validation, role authorization.
- `services.py` — calculations (tiered assistance quote with pinned floor-before-cap order, per-item-rounded deduction schedule, interval-merge creditable marketing days, projected/final deficiency waiver amounts, holdover penalty), lookups with per-entity 404s, field validators, lazy offer expiry, and cascade helpers (withdraw, eviction filing, waiver execution, case completion).

**Endpoint count**: 76 routes implemented (73 declared endpoints; case sub-resource list paths, loan waiver list, etc. included — the full PRD §4 locator table).

**Logical clock**: a module-level `LogicalClock` instance in `db.py`, initialized to exactly `2026-08-01T00:00:00Z` at every process boot, advanced only via `POST /_clock/set_current_utc` (ServicingAdmin-only). All temporal rules (offer expiry, 10-day vacate notice, 24h inspection notice, 90-day marketing minimum, 3-day holdover grace, 30-day recording deadline, creditable-days evaluation) read this clock. Offer expiry is lazy: `OFFERED` agreements flip to `EXPIRED` on read or action when past `offer_expires_at` (no sweep on clock-set).

**Boot confirmation**: smoke-tested `start.sh` on ports 18333/18444-18446. Verified end-to-end: full DIL pipeline (intake → eligibility → marketing (90 creditable days) → title clearance → agreement negotiate/accept → handover inspection → disbursement with SoD (approve/release by different officers) → RECORDING_PENDING → waiver document → deed recording confirm → case COMPLETED, waiver EXECUTED with final amount, loan DEED_IN_LIEU_COMPLETED + synced + deficiency zeroed), the full CFK path with deduction rounding (22499+37499=59998) and completion cascade, plus error-path spot checks (401/403/404, ERR_INVALID_ENUM, ERR_STALE_VERSION, ERR_INSPECTOR_SCHEDULE_CONFLICT-before-ERR_INSPECTION_TOO_SOON, ERR_KEYS_NOT_RETURNED, ERR_SOD_RELEASER_EQUALS_APPROVER, lazy expiry). Fresh-boot isolation confirmed: on restart the store is empty and the clock reads the 2026-08-01 default.

## Step 5: Generate Unit Tests — 2026-08-14T21:10:00.000Z

Done. Complete test infrastructure generated for task_1833.

## Deliverables

**`test_helpers/` (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/test_helpers/`:
- `types.py` — 8 roles + 18 status/domain enums + 15 entity TypedDicts (all common-fields entities)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (76 methods)
- `api_errors.py` — full 47-entry error catalog with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_same_instant` (format-tolerant logical-clock comparison), `assert_assistance_conservation` / `assert_debt_conservation` invariant checkers
- `factories.py`, `constants.py` (tiers/floor/cap, deduction bases, temporal thresholds, standard economics)
- `test_users.py` — `TEST_USERS` constants + per-role `make_*_headers` builders (mandatory `make_borrower_headers` for the entity-backed Borrower role)
- `fixtures.py` — six-tier composite pipeline builders (marketing → title → terms → agreement-active → disbursement-pending → recording-pending/submitted → completed; escalated/filed eviction), all built from PRD endpoints with `get_success_data`

**`test_suite/` (10 files)** — `conftest.py` plus 9 concern-clustered test files (`test_01` boarding … `test_09` security/404 sweep).

## Test counts

- **Queue A (Difficulty): 46 tests** — all 23 instances covered at exactly 2 tests each.
- **Queue B (Corner): 68 tests** — 68 of 69 non-stub instances at 1 test each; the 8 `excluded_because:` stubs were not translated (all cross-references verified to resolve to real difficulty instances).

## Instances skipped (1)

- `Corner/entities/loan_client_supplied_id_input_ignored` — unique-derivability failure: PRD §2.5 states "The `id` is a server-minted UUID carrying no type prefix." but never states whether an undeclared client-supplied `id` in a create payload is ignored or rejected as malformed; a PRD-only reader could ship either, so the asserted outcome (request succeeds with a different server id) is not uniquely determined.

## Verification performed

- All files compile; `import test_helpers` resolves against the installed framework; `pytest --collect-only` collects **114 tests** cleanly.
- Tag audit: every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line; all 114 tags resolve to real instances in the source yamls; queue A ≥2/instance and queue B ≥1/non-stub-instance confirmed programmatically.
- Citation audit: all **170 quoted PRD sentences across docstrings verified verbatim** against `workspace/PRD.md` (grep-level match); no endpoint-titular-only citations.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in any generated comment or docstring.
- Initial-`version == 1` assertions from two index instances were deliberately omitted (PRD §2.5 pins increment semantics, not the starting value); all other asserted values (3288 per-diem, 550000 provisional, 59998 per-item-rounded deductions, 475002/215002 finals, 2601928/2615080 waiver variants, 90/89-day and grace-day-3/4 boundaries) trace to verbatim PRD rules.

## Step 7: Run Tests and Iterate — 2026-08-14T21:25:00.000Z

All 8 rounds are clean: 114/114 passed in every round.

## Summary

**Iterations run:** 2 (sweep 1 surfaced failures; fix applied; sweep 2 fully clean — 8/8 rounds × 114/114 tests, no flakiness).

**Tests deleted:** none.

**Failing tests (union across rounds, both deterministic — failed in all 8 rounds):**
- `test_04_agreement_negotiation.py::test_expired_offer_accept_reports_offer_expired` — "Expected error_id 'ERR_OFFER_EXPIRED', got 'ERR_AGREEMENT_INVALID_STATE'"
- `test_04_agreement_negotiation.py::test_expired_offer_flips_agreement_expired` — same assertion

**Diagnostic outcome:** Both tests passed STEP 1 (PRD §3.5 verbatim: "on an accept or counter the expiry guard reports `ERR_OFFER_EXPIRED` and the agreement then flips to `EXPIRED`, while plain reads flip it silently" — coverage and unique derivability hold) and STEP 2 (fixture `_setup_expired_offer_with_lien` builds PRD-consistent preconditions; request and assertion are faithful). Failure was an implementation bug.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/workspace/implementation/app.py` — `accept_agreement()` and `counter_agreement()`: removed the pre-emptive `lazy_expire_agreement(rec)` call that ran before the pinned guard ladder. The premature call silently flipped an OFFERED-but-lapsed agreement to EXPIRED, so the subsequent state check fired `ERR_AGREEMENT_INVALID_STATE` instead of the PRD-pinned `ERR_OFFER_EXPIRED`. The existing inline expiry guard (after state and ownership checks) now performs the flip-to-EXPIRED + `ERR_OFFER_EXPIRED` raise itself, exactly per PRD §3.5's pinned order. The silent lazy flip remains in place for plain reads (`get_agreement`, case-agreements list), offer, reoffer, and terminate, as PRD specifies.

**Fixes applied to `test_helpers/` and `test_suite/`:** none needed.

## Step 8: Finalize PRD — 2026-08-14T21:35:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/workspace/PRD_FINALIZED.md` produced. It is a byte-identical copy of PRD.md — **zero edits were warranted**.

## Line counts

- PRD.md: 354 lines
- PRD_FINALIZED.md: 354 lines
- Delta: 0 lines, 0.0%

## Changes

None. The sole `<step_7_diff>` item is an `implementation/` fix (removal of the pre-emptive `lazy_expire_agreement(rec)` in `accept_agreement()` and `counter_agreement()`, app.py) that brought the code **into conformance with behavior the PRD already pins verbatim** — it revealed no PRD silence and no PRD/impl mismatch surviving the fix. Per the method ("Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open … or impl mismatch with PRD.md"), there was nothing to trace an edit to. Step 7's own diagnostic confirms this: both failing tests passed STEP 1 (PRD coverage and unique derivability hold) and STEP 2; the failure was purely an implementation bug. No tests were deleted and no `test_helpers/`/`test_suite/` fixes were applied, so no other edit triggers exist.

## Pre-edit search log (one entry per step_7_diff item; the item resolved to no edit)

**Item: implementation fix to `accept_agreement()` / `counter_agreement()` expiry handling**

- **(a) Subject identified:** Order and reporting of the offer-expiry guard on agreement accept/counter — whether the agreement flips OFFERED→EXPIRED silently before the state guard (old buggy code) or the expiry guard itself flips and raises `ERR_OFFER_EXPIRED` after the state and ownership checks (fixed code).
- **(b) Impl paths enumerated and read:**
  - `workspace/implementation/app.py:966-1018` (`accept_agreement`) — guard order now state (`ERR_AGREEMENT_INVALID_STATE`) → ownership (`ERR_FORBIDDEN`) → expiry (flip to EXPIRED + `touch` + `ERR_OFFER_EXPIRED`) → junior-lien gate.
  - `workspace/implementation/app.py:905-932` (`counter_agreement`) — same state → ownership → expiry ladder, then the ten-day vacate notice.
  - `workspace/implementation/app.py:877-886` (`get_agreement`), `app.py:488-499` (`case_agreements_ep`, flip at line 497), `app.py:889-902` (`offer_agreement`, line 895), `app.py:935-963` (`reoffer_agreement`, line 942), `app.py:1021-1030` (`terminate_agreement`, line 1025) — all retain the silent pre-flip via `lazy_expire_agreement`.
  - `workspace/implementation/services.py:291-301` (`lazy_expire_agreement`) — flips only `OFFERED` agreements past `offer_expires_at`, with `touch`.
  - `workspace/implementation/db.py:70-72` (`touch` — updates `updated_at` and bumps `version`).
  - Tests: `test_suite/test_04_agreement_negotiation.py:392-438` (fixture + both formerly failing tests), each quoting the PRD sentences they derive from.
  - PRD passages checked against all of the above: §1/clock (line 78), §2.10 priority ladder (lines 104, 106), §3.5 (lines 160, 164, 166, 168).
- **(c) Wording adjustment:** None made, because none was needed — PRD §3.5 already uniquely determines the fixed behavior at every enumerated path: line 164 pins the accept guard order verbatim ("the agreement must be `OFFERED` … ownership must hold … and the offer must not have lapsed (`ERR_OFFER_EXPIRED`) — this temporal check is evaluated before any lien-clearance check"); line 160 pins the counter ("valid only from `OFFERED` and only while the offer has not lapsed … rejected with `ERR_OFFER_EXPIRED`"); line 166 pins the flip semantics ("on an accept or counter the expiry guard reports `ERR_OFFER_EXPIRED` and the agreement then flips to `EXPIRED`, while plain reads flip it silently"); and lines 78/168 cover the retained silent pre-flip on offer/reoffer/terminate (lazy flip on "read or acted upon", then terminal-state rejection with the state error). A fresh implementer reading PRD.md alone already derives the exact fixed code, so any additional wording could only risk a new mismatch, not remove one.

## Step 9: Complete PRD — 2026-08-14T21:45:00.000Z

All 28 edits applied cleanly — same line count (354), all in-paragraph inserts/revisions. Here is the summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (354 lines, 64,784 chars) → `PRD_COMPLETED.md` (354 lines, 70,867 chars). Char delta: **+6,083**. 28 lines revised in place; no lines added or removed; no new sections.

**Counts:** 27 ambiguity-pins, 6 mismatch-revisions (33 pins total across 28 edited paragraphs; some paragraphs carry two pins).

**Ambiguity-pins (PRD silent → pinned to impl):**
- §2.3 — insert — ambiguity — invalid `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `total_count` counts all post-filter matches; `has_more` ⇔ `offset`+`limit` < `total_count`; filters match literally, unknown value → empty page — response.py:53-94
- §2.4 — revise — ambiguity — clock may be set to any instant, forward or backward ("advances" unpinned) — db.py:44-45, app.py:84-90
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — db.py:63-67
- §2.5 — insert — ambiguity — all server timestamps (incl. envelope `api_request_timestamp`, action stamps) read from the logical clock — response.py:15-19, db.py:63-72
- §2.7 — insert — ambiguity — version-match evaluated after state/uniqueness, before temporal/fiscal (after one-active-agreement, before vacate-notice; after lien state, before settlement ceiling) — app.py:831-844, app.py:795-803
- §2.7 — revise — ambiguity — version fields supplied to non-guarded endpoints are ignored (not rejected) — app.py (no other endpoint reads a version field)
- §2.9 — insert — ambiguity — undefined route → `ERR_INVALID_REQUEST` (404); unsupported method → `ERR_INVALID_REQUEST` (405) — app.py:70-77
- §2.10 — insert — ambiguity — rung 4: empty string counts as absent; non-JSON-object body is malformed — services.py:181-195
- §3.1 — insert — ambiguity — borrower registration: all four fields required — app.py:179-186
- §3.1 — revise — ambiguity — `state_code` recorded as supplied (no two-letter validation); `address_line`/`county`/`state_code`/`occupancy_type` required; multiple properties per loan allowed, quote reads earliest-registered — app.py:213-223, app.py:851
- §3.2 — insert — ambiguity — case opening performs no loan-status check and no per-loan uniqueness check — app.py:251-280
- §3.3 — revise — ambiguity — future `list_date` rejected with `ERR_INVALID_REQUEST`, evaluated with input validations before the case-state check — app.py:572-580
- §3.3 — insert — ambiguity — closing stamps `closed_at` with the current logical timestamp — services.py:507-516
- §3.3 — revise — ambiguity — creditable-days: suspension endpoints taken as calendar dates of `started_at`/`ended_at`; clamp-emptied intervals dropped; sort by start date; merge when start ≤ running end + 1 day (back-to-back coalesce) — services.py:372-407
- §3.4 — insert — ambiguity — ordering a commitment requires case `TITLE_REVIEW` (`ERR_CASE_INVALID_STATE`); no per-case uniqueness gate — app.py:676-696
- §3.4 — insert — ambiguity — successful lien release answers 200 with the updated lien — app.py:813
- §3.4 — revise — ambiguity — certify-title evaluates the case's most recently created commitment — app.py:397-401
- §3.5 — revise — ambiguity — DRAFT supersession happens during creation processing (survives a subsequent property-lookup failure); quote reads earliest-registered property of the loan; none registered → `ERR_PROPERTY_NOT_FOUND` — app.py:845-856
- §3.5 — insert — ambiguity — `offer_valid_days` is a required integer on offer — app.py:894
- §3.5 — revise — ambiguity — counter guard order pinned as state → ownership → expiry (same as acceptance) — app.py:914-924
- §3.5 — insert — ambiguity — `offer_valid_days` required integer on reoffer — app.py:941
- §3.5 — revise — ambiguity — acceptance stamps `accepted_at`; lien-clearance check reads the case's most recently created title commitment — app.py:986-993
- §3.5 — insert — ambiguity — waiver created with `waived_amount_cents` and `pre_waiver_deficiency_cents` initialized to zero — app.py:1005-1015
- §3.5 — revise — ambiguity — `remaining_assistance_cents` applicable-agreement selection: most recently created `ACCEPTED`/`COMPLETED` if any, else most recently created overall; assistance = `final_assistance_cents` only when set on an `ACCEPTED`/`COMPLETED` agreement — services.py:435-456
- §3.6 — insert — ambiguity — `scheduled_end` ≤ `scheduled_start` rejected with `ERR_INVALID_REQUEST` — app.py:1064-1065
- §3.7 — insert — ambiguity — `agreement_id` must resolve but is not cross-checked against the addressed case — app.py:1261-1264
- §3.8 — insert — ambiguity — when several waivers exist (one per acceptance), the earliest-created is operative for gate and execution — services.py:471-475, app.py:1492
- §3.8 — revise — ambiguity — recording create against `CASH_FOR_KEYS` → `ERR_INVALID_REQUEST`; creation not blocked by an existing package — app.py:1444-1449
- §3.9 — insert — ambiguity — escalation requires an accepted agreement; absence → `ERR_AGREEMENT_NOT_FOUND` — app.py:423-426

**Mismatch-revisions (PRD described different behavior → revised to impl):**
- §2.1 — revise — mismatch — borrower "reads only own cases' sub-resources" carved out: `GET /listings/{id}` and `GET /listings/{id}/suspensions` perform no borrower-ownership check — app.py:600-606, app.py:661-669
- §2.10 — revise — mismatch — rung 2 split: role authorization at rung 2, but entity-backed ownership evaluated only after existence, and after the state check where §3 pins it (counter/accept; inspector create-report/submit/no-access) — app.py:905-933, app.py:966-984, app.py:1125-1136, app.py:1160-1164, app.py:1207-1212
- §2.10 — insert — mismatch — recording confirmation evaluates waiver-documentation (`ERR_WAIVER_NOT_DOCUMENTED`) before the recording-deadline check, overriding the ladder's temporal-before-referential family order — app.py:1492-1499
- §3.3 — revise — mismatch — "any read recomputes" narrowed: only the direct `GET /listings/{id}` recomputes creditable days; collection reads return the stored value — app.py:600-606 vs app.py:467-475
- §3.6 — revise — mismatch — a line item missing `item_code`/`severity` is rejected with `ERR_INVALID_ENUM` (not the rung-4 default `ERR_INVALID_REQUEST`); also pins `broom_clean_verified`/`keys_returned_count` required and `line_items` optional-default-empty — app.py:1144-1159
- §3.6 — revise — mismatch — submit cascade movements are conditional on source states still holding (stale draft after appointment cancel or case leaving `VACATE_PENDING` still prices/records result but moves nothing) — app.py:1224-1249

The completed file is at `/home/ubuntu/github/CodingPRD/tasks/task_1833_deed_lieu_cash_keys_administration/workspace/PRD_COMPLETED.md`.
