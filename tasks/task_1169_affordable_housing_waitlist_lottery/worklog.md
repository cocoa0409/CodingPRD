# Worklog — task_1169_affordable_housing_waitlist_lottery

## Step 1: Create Task Directory — 2026-08-11T07:56:00.000Z

Task directory `tasks/task_1169_affordable_housing_waitlist_lottery/` and its `workspace/` subdirectory were pre-assigned and already exist (index 1169 assigned by pipeline dispatcher; Step 1 auto-index scan skipped per instructions). Verified present on disk.

## Step 2: Generate Scaffold — 2026-08-11T09:11:00.000Z

Scaffold generation complete. All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_1169_affordable_housing_waitlist_lottery/` and verified on disk.

**Design (difficulty: beyond-Expert as requested — density over volume):** Quota/allocation archetype blended with compliance/audit; flat entity topology (FK-linked peers, no nested URLs); cyclic state-machine shape; segregation-of-duties role model; immediate consistency. Layers: optimistic concurrency, cascading side effects, selector policy, scheduled actions (logical clock, default `2026-05-01T00:00:00Z`).

**Counts:**
- **14 entities**: Property, Unit, OccupancyStandard, AmiLimit, ApplicationCampaign, Applicant, Application, PreferenceClaim, IncomeCertification, LotteryRun, WaitlistEntry, UnitOffer, PurgeRun, ComplianceReport
- **53 endpoints** (incl. `POST /_clock/set_current_utc`); every FK reverse-reachable per lint check (f)
- **10 state machines** — 4 cyclic on different entities (Application review loop, WaitlistEntry offer/refusal loop, IncomeCertification docs loop, ComplianceReport return loop) plus guarded/compound campaign and conditional-cascade unit machines
- **9 calculations** — dual variants on two domains (provisional-vs-certified income; calendar-quarter-vs-rolling-90-day report aggregation); combinatorial modes (a) preference-tier branching, (b) pinned per-source whole-dollar rounding, (c) pinned offer-selector evaluation order; seeded sha256 lottery (no random/id participation in decisions)
- **12 validation tiers** (auth → authz → shape → existence → OCC → state → safety/segregation → temporal → constraint → referential → fiscal → overlap), **29 error codes**, **8 roles** (Applicant entity-backed; segregation between LotteryAdministrator and ComplianceOfficer enforced by X-User-ID), **2 OCC rules** on campaign version
- **§1.8: 18 instances** (9 rules × 2, all differentiation clauses honored — different entity domains, modes, pairs, metrics, resources, conserved quantities)
- **§1.9: 65 entries = 56 active instances + 9 `excluded_because` stubs** across all nine claim-extraction-guide sections

**Verification evidence:**
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 1184 calls scanned, 0 violations
- All three files parse as valid YAML; correct top-level keys (`SCAFFOLD.yaml` has neither design key; design files carry only their single key)
- Custom audit script: 82 instance names unique across both files; zero unbound `${var}` placeholders (setup bindings carried into triggers); all `grounds:` resolve to §1.1–§1.7 elements; all stub `difficulty_instance` targets exist; all 29 error codes referenced by at least one test
- Every numeric literal in asserts recomputed by code and confirmed (e.g., 1800400 vs 1800500 rounding divergence, boundary income 4000000 == limit → ELIGIBLE with 10000 bp, rate 6667/5000 bp, rolling-window start 2026-03-17, cert valid_until 2026-12-07)

No sibling task directories were inspected; the scaffold was generated purely from the scenario text and the skill specification.

Orchestrator verification: all three files exist on disk and parse as valid YAML with the correct top-level keys.

## Step 3: Copy Shared Files — 2026-08-11T09:12:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1169_affordable_housing_waitlist_lottery/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T09:25:00.000Z

**Output:** `workspace/PRD.md` — 54,662 bytes, 295 lines (not truncated; ends at the §5 error table).

**Section list:**
- §1 Introduction (2 paragraphs: announcement/marketing, preference verification, seeded lottery, income certification, unit matching, offer/refusal cycle, purge/reopen, funding-agency reporting)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 8 roles with identity translations, action-level role mapping), 2.2 API Response Structure (byte-identical to canonical block — verified `True`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (UUID `id`, ISO 8601 `created_at`/`updated_at`, integer `version`, cascade-mutation semantics), 2.5 Logical Clock (startup default `2026-05-01T00:00:00Z`, explicit sweeps), 2.6 OCC on campaign-writing operations, 2.7 Money/Counts/Rounding, 2.8 Derived Counters, 2.9 Segregation of Duties, 2.10 Validation Pipeline (all 12 priority stages in order)
- §3 Business Logic — 8 subsections organized by lifecycle: 3.1 property/unit config, 3.2 campaign authoring & window, 3.3 application intake & preference claims, 3.4 income certification, 3.5 sealed lottery & ranking, 3.6 offers & refusal cycle, 3.7 purges & reopening, 3.8 compliance reporting
- §4 Endpoint Definitions — 4-column table, all **53/53** scaffold endpoints present
- §5 Error Code Catalogue — 2-column table, all **28/28** error IDs present

**Hard-contract verification evidence (scripted):**
- Contract 1 (field-name coverage): **106 required names, 0 missing** (entity fields + endpoint inputs + query params + common fields)
- Contract 3 (§3 path purity): **515 backtick tokens scanned, 0** path/method violations
- Contract 2 (rule coverage, manual walk): all 12 validation priorities expressed in order in §2.10; both OCC rules with `expected_campaign_version` + `ERR_STALE_VERSION` (412) in §2.6/§3.5/§3.7; all 49 transitions across 9 state machines with preconditions and side effects; all 9 calculations in precise operator-free prose (including the pinned per-source whole-dollar rounding worked example and the pinned eligibility→boost→ranking offer-selection order); all enum/state values present; every error ID appears in §1–§3 prose
- §2.2 confirmed byte-identical to `section-2.2-response-structure.md`

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

Orchestrator verification: PRD.md exists on disk (54,662 bytes, 295 lines), ends at the §5 error table.

## Step 5: Generate Unit Tests — 2026-08-11T09:55:00.000Z

Generation complete and verified on disk.

**Files written**

`test_helpers/` (9 files): `__init__.py` (barrel export), `types.py` (14 entity TypedDicts + 14 enums), `api_client.py` (57 methods — one per PRD §4 endpoint incl. `/_clock/set_current_utc`), `api_errors.py` (28 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + property-bucket / entry-census invariants), `factories.py`, `constants.py` (OFFER_RESPONSE_DAYS=10, CERTIFICATION_VALID_DAYS=180, MAX_REFUSALS=2, startup clock, standard windows), `test_users.py` (8 roles; `make_applicant_headers(applicant_id)` for the entity-backed Applicant role), `fixtures.py` (composite pipelines: `new_open_campaign`, `new_verified_application`, `run_published_lottery`, `certify_household_income`, `setup_leasing_pipeline`, `setup_leasing_with_pending_offer`, `setup_purge_notices_sent`, offer accept/decline with owner resolution).

`test_suite/` (11 files): `conftest.py` + `test_01_property_and_units` (8), `test_02_campaign_lifecycle` (7), `test_03_application_intake` (9), `test_04_review_and_claims` (7), `test_05_income_certification` (13), `test_06_lottery` (8), `test_07_offers` (18), `test_08_purges` (7), `test_09_compliance_reports` (8), `test_10_rbac_and_auth` (6).

**Test counts**
- Queue A (Difficulty): 36 tests over 18/18 instances (exactly 2 per instance)
- Queue B (Corner): 55 tests over 55/55 non-stub instances (1 per instance)
- Total: 91 tests, 73 distinct `Design:` tags

**Skipped instances**: none. All 73 non-stub instances passed the PRD-first two-condition filter (the two validation-priority instances are legitimate because PRD §2.10/§3.4 state the fixed check ordering verbatim). The 9 `excluded_because:` stubs were not translated; all their difficulty-instance cross-references resolve.

**Notable derivability adjustments** (kept within PRD-covered assertions, no weakening of covered rules): exact initial `version == 1` values are never hard-coded (PRD §2.4 pins only "+1 per mutation", so version assertions are relative to a captured create-response version).

**Verification evidence**
- `python3 -m py_compile` on all 20 `.py` files: OK
- `PYTHONPATH=. python3 -c "import test_helpers"`: OK
- Tag audit script: 91 tests, every test function carries exactly one `Design:` tag as the final docstring line; zero missing/extra/shortfall vs both YAML indices
- Verbatim-citation sweep: every ≥8-word quoted fragment in every docstring matches `workspace/PRD.md` (whitespace-normalized): 0 failures
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold"/§1.x references in generated code

## Step 6: Generate Implementation — 2026-08-11T09:55:00.000Z

Generation complete. Implementation written to `workspace/implementation/`: `start.sh` (executable, conditional flask install, `exec python3 app.py`), `requirements.txt` (flask>=3.0.0), `app.py` (Flask entry: ApiError/404/405/500 handlers with canonical error envelope, blueprint registration, binds 0.0.0.0:$PORT), `db.py`, `errors.py`, `helpers.py`, `middleware.py`, `response.py`, `services.py` (16.5 KB domain logic), `routes/__init__.py` + `routes/core.py` (53 route registrations).

**Subagent route verification:** 53/53 (method, path) route pairs in the implementation match SCAFFOLD.yaml's declared endpoints exactly (subagent's returned message was cut off after reporting this; the orchestrator completed the remaining verification from disk).

**Orchestrator disk + boot verification:**
- `python3 -m py_compile` on all `.py` files: OK
- Boot smoke test (3 launches on free ports): server boots in ≤2s via `bash start.sh` with `PORT` set, binds 0.0.0.0, no reloader
- `GET /properties` → 404 canonical envelope `ERR_NOT_FOUND` (correct — SCAFFOLD declares POST /properties + GET /properties/<pid>, no collection GET)
- `POST /properties` without headers → 401 `ERR_UNAUTHENTICATED`; with unknown role → 401 (validation tier 1 correct)
- `POST /properties` as HousingDeveloper with partial payload → 400 `ERR_INVALID_REQUEST` naming the missing field; with full payload → **HTTP 201** with canonical object envelope: UUID id, `created_at`/`updated_at` = `2026-05-01T00:00:00Z` (logical clock default), `version: 1`, all five derived unit counters = 0

## Step 7: Run Tests and Iterate — 2026-08-11T10:21:00.000Z

All 8 rounds pass: 91/91 in every round. Clean sweep achieved.

- **Iterations run:** 2 sweeps (8 parallel rounds each). First sweep: 89/91 in all 8 rounds (same 2 deterministic failures everywhere, no flakiness). Second sweep after fixes: 91/91 in all 8 rounds.

- **Tests deleted:** None. Both failing tests traced to verbatim PRD sentences and were faithful in setup, request, and assertion.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `implementation/`:** 2

  1. `workspace/implementation/db.py` — `_DEFAULT_CLOCK` changed from `"2026-05-01T00:00:00Z"` to `"2026-05-01T00:00:00.000Z"`. PRD §2.4 requires `created_at`/`updated_at` to be "an ISO 8601 UTC timestamp with three fractional digits"; the startup-default clock was leaking through unstamped with `.000`, failing `test_applicant_register_returns_system_minted_fields`. All datetime comparisons go through `parse_iso`, which accepts both forms, and no test asserts the raw non-ms clock echo, so the change is safe.

  2. `workspace/implementation/routes/core.py` (`transition_lottery_run`, SEAL branch) + `services.py` (`execute_lottery`) + `db.py` (`Store.lottery_snapshots`) — PRD §3.5: sealing snapshots "the number of the campaign's applications in `VERIFIED` status at that exact instant" and execution "generates one waitlist entry per snapshotted application". The implementation was re-querying the live VERIFIED set at EXECUTE time, so an application verified between SEAL and EXECUTE was wrongly included (`test_seal_snapshot_excludes_late_verified_application`, `assert 2 == 1`). SEAL now freezes the eligible application id list into an internal, never-serialized `Store.lottery_snapshots` map (kept out of `_pub`, so no non-PRD response field leaks), and EXECUTE draws exclusively from that frozen snapshot.

No storage is persisted anywhere — state remains in-memory dicts only, so per-test-server restarts still guarantee a fresh boot.

Orchestrator verification: all 8 `results.{1..8}.json` files on disk, each `passed=91, failed=0, total=91, errors=0`.

## Step 8: Finalize PRD — 2026-08-11T10:24:00.000Z

`execute_lottery` is called only from the EXECUTE branch (`routes/core.py:1109`), which requires the run to be SEALED — and SEAL always populates `lottery_snapshots` (`routes/core.py:1100`). The `None` fallback is unreachable via the API, so "drawn exclusively from the frozen seal-time snapshot" describes every reachable path. PRD_FINALIZED.md is written and verified.

**Line counts / delta:** PRD.md 295 lines, PRD_FINALIZED.md 295 lines (0% line-count delta; 3 lines revised in place, no insertions of new lines).

**Changes (3 edits, both Step 7 items covered):**

- §2.5 (line 87) — revise — startup clock default changed from `2026-05-01T00:00:00Z` to `2026-05-01T00:00:00.000Z`, plus a clause stating the clock serializes in §2.4's three-fractional-digit format wherever it appears — `implementation/db.py:13` (`_DEFAULT_CLOCK`), `db.py:31-36` (`format_iso`), `routes/core.py:46` (`current_utc` echo).
- §3.5 (line 166) — revise — sealing now snapshots the *set* of VERIFIED applications (frozen at the sealing instant), `eligible_application_count` records its size, and EXECUTE draws one waitlist entry per snapshotted application exclusively from that frozen set (late-verified applications excluded) — `implementation/routes/core.py:1093-1104`, `implementation/services.py:71-84`, `implementation/db.py:79-82`.
- §4 endpoint table (line 260) — revise — `/_clock/set_current_utc` row's parenthetical default updated to `2026-05-01T00:00:00.000Z` to match the §2.5 edit — `implementation/db.py:13`.

**Per-edit pre-edit search log:**

*Edit 1 (§2.5 + line 260, clock default format):*
- (a) Subject: serialized string form of the logical clock, specifically the startup default.
- (b) Enumerated/read: `db.py:10-14` (`_DEFAULT_CLOCK` stored pre-formatted with `.000`), `db.py:17-28` (`set_current_utc`/`get_current_utc`/`now_iso`), `db.py:31-36` (`format_iso` always emits three fractional digits), `db.py:84-92` (`new_record`/`touch` stamp `created_at`/`updated_at` from the same clock string), `routes/core.py:39-46` (`/_clock/set_current_utc` echoes `get_current_utc()` verbatim), and every `now_iso()` consumer (`services.py:225,268,291,333,359`; `routes/core.py:646,774,788,1103,1111,1118,1209,1229,1603`) — all emit the identical clock string.
- (c) Wording adjustment: kept the instant identical and added "rendered in the three-fractional-digit format of §2.4 ... wherever it appears (for example in `current_utc` and in every clock-stamped field)" so the claim covers all enumerated paths without asserting a per-field rule beyond what §2.4 already pins.

*Edit 2 (§3.5, seal-time snapshot):*
- (a) Subject: which applications receive waitlist entries at EXECUTE.
- (b) Enumerated/read: `routes/core.py:1090-1104` (SEAL computes `eligible_ids` from live VERIFIED set and freezes them into `Store.lottery_snapshots`, sets `eligible_application_count = len(eligible_ids)`), `routes/core.py:1105-1112` (EXECUTE requires SEALED, calls `execute_lottery`), `services.py:71-130` (execution iterates only snapshot ids; ranking/entry creation consume only that list), `db.py:78-82` (snapshot map is internal, never serialized — confirmed no `_pub` exposure), and grep-confirmed `execute_lottery` has exactly one caller (`routes/core.py:1109`), so the `snapshot_ids is None` fallback at `services.py:78-83` is unreachable through the API.
- (c) Wording adjustment: scoped strictly to the SEAL/EXECUTE transition — "snapshotting the campaign's applications in VERIFIED status at that exact instant: the frozen set ... is the snapshot, and `eligible_application_count` records its size" and "drawn exclusively from the frozen seal-time snapshot, so an application verified after sealing is not included". No claim about serialization or about any other endpoint; PUBLISH/VOID paths verified untouched by the wording.

No test-suite, test-helper, or other edits were needed (Step 7 reported none), and no other PRD section referenced the bare clock string or the snapshot semantics — verified by grep over PRD_FINALIZED.md.

Orchestrator verification: PRD_FINALIZED.md on disk (55,053 bytes, 295 lines); diff vs PRD.md shows exactly the 3 in-place line revisions described above, nothing else.


## Step 9: Complete PRD — 2026-08-11T10:42:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written — a minimal patch over PRD_FINALIZED.md with all section headers unchanged and every edit an inline insert/revision inside existing paragraphs.

**Size**: PRD_FINALIZED.md 295 lines / 55,053 chars → PRD_COMPLETED.md 298 lines / 60,482 chars (char-delta +5,389; +3 lines from the two new bullets and one new paragraph in §2.10).

**Counts**: 21 ambiguity-pins, 6 mismatch-revisions (27 changed regions total).

**Changes** (section — kind — class — what — impl ref):

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to wall-clock at serve time (the only wall-clock read) — implementation/response.py:17-23
- §2.2 — insert — ambiguity — undefined path / unsupported method → `ERR_NOT_FOUND` 404 envelope — implementation/app.py:20-26
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, limit outside 1–100, negative offset) → `ERR_INVALID_REQUEST`; `has_more` = `offset + page size < total_count`; unrecognized filter values yield empty pages — implementation/helpers.py:95-107, implementation/response.py:36
- §2.4 — insert — ambiguity — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — implementation/db.py:88-91
- §2.5 — insert — ambiguity — clock accepts any instant, earlier or later (no monotonicity check) — implementation/routes/core.py:39-46
- §2.10 stage 3 — revise — mismatch — non-empty claim evidence (`ERR_PREFERENCE_EVIDENCE_REQUIRED`) moved from stage 9 to stage 3 (impl checks it before existence) — implementation/routes/core.py:677-685
- §2.10 stage 9 — revise — mismatch — evidence item removed from stage 9 list accordingly
- §2.10 closing — revise — mismatch — new paragraph pinning: action-conditional payload fields (`rejection_reason`, `denial_reason`, `void_reason`, `return_reason`, `new_evidence_ref`, `required_docs`, `income_sources`, reopen window pair) validated after state preconditions (entry-removal `removal_reason` is the exception, validated as plain shape); applicant ownership judged after existence (dangling id → 404, not 403); identifiers resolve before cross-field rules — implementation/routes/core.py:649-655, 779-795, 907-933, 979-985, 1125-1129, 1219-1226, 1610-1614, 501-506
- §3.1 — revise — mismatch — `state_code` recorded as supplied (no two-letter check) — implementation/routes/core.py:61
- §3.1 — revise — mismatch — `unit_number` uniqueness not enforced by the server — implementation/routes/core.py:93-120
- §3.1 — insert — ambiguity — unit service `action` vocabulary `PLACE_OUT_OF_SERVICE`/`RETURN_TO_SERVICE` — implementation/routes/core.py:154
- §3.1 — insert — ambiguity — `uniqueness_scope` serialized as colon-joined `{property_id}:{bedroom_count}` and `{property_id}:{household_size}:{ami_tier}` — implementation/routes/core.py:206, 267
- §3.2 — insert — ambiguity — campaign creation requires close strictly after open (`ERR_INVALID_REQUEST`) — implementation/routes/core.py:342-343
- §3.2 — insert — ambiguity — campaign transition `action` vocabulary `ANNOUNCE`/`OPEN`/`CLOSE`/`REOPEN`; announcement reads the stored channel list — implementation/routes/core.py:399, 416
- §3.3 — insert — ambiguity — `confirmation_code` is a freshly minted UUID string — implementation/routes/core.py:536
- §3.3 — insert — ambiguity — review `action` vocabulary (`BEGIN_REVIEW`/`REQUEST_INFO`/`SUBMIT_INFO`/`COMPLETE_VERIFICATION`/`REJECT`); the `note` is accepted but not persisted — implementation/routes/core.py:605-606, 625-628
- §3.3 — insert — ambiguity — `verified_preference_categories` serialized in canonical order `LOCAL_RESIDENT`, `VETERAN`, `ACCESSIBILITY` — implementation/helpers.py:137-148
- §3.3 — insert — ambiguity — claim filing gated on application in `SUBMITTED`/`UNDER_REVIEW`/`NEEDS_INFO` (else `ERR_INVALID_STATE`); claim `action` vocabulary `VERIFY`/`DENY`/`APPEAL`; appeal retains prior `decided_at`/`decided_by` — implementation/routes/core.py:688-689, 752, 798-800
- §3.4 — insert — ambiguity — cert advance `action` vocabulary (`REQUEST_DOCS`/`SUBMIT_DOCS`/`CERTIFY`/`DENY`); income-source entry typing (source_type non-empty string, amount any JSON number, periods a JSON integer) — implementation/routes/core.py:891, 922-933
- §3.4 — insert — ambiguity — `CERTIFY` possible only from `DOCS_RECEIVED` (else `ERR_INVALID_STATE`) — implementation/routes/core.py:937-938
- §3.5 — insert — ambiguity — lottery transition `action` vocabulary `SEAL`/`EXECUTE`/`PUBLISH`/`VOID` — implementation/routes/core.py:1087
- §3.6 — insert — ambiguity — generation gated only on a `PUBLISHED` run (campaign status not consulted); `LEASING` flip only on a batch producing ≥1 offer; `units_considered` counts all `AVAILABLE` units walked, including occupancy-skipped ones — implementation/routes/core.py:1249-1256, implementation/services.py:148-176
- §3.6 — insert — ambiguity — only `PENDING` offers may be responded to (else `ERR_INVALID_STATE`) — implementation/routes/core.py:1329-1330
- §3.6 — revise — mismatch — accept-side certification gate changed from "valid_until still in the future" to "not yet passed" (equality passes) — implementation/routes/core.py:1337-1339
- §3.6 — revise — mismatch — admin removal accepts any removal-reason code (`MAX_REFUSALS`/`PURGED`/`LOTTERY_VOIDED`/`ADMIN_REMOVED`), recorded as supplied; missing/unrecognized → `ERR_INVALID_REQUEST` — implementation/routes/core.py:1219-1223
- §3.7 — insert — ambiguity — negative `notice_response_days` rejected (`ERR_INVALID_REQUEST`); purge `action` vocabulary `SEND_NOTICES`/`EXECUTE`/`CANCEL`; confirm-interest requires the entry itself `RANKED` — implementation/routes/core.py:1375-1377, 1437, 1200-1201
- §3.8 — insert — ambiguity — `ROLLING_90_DAY` requires `period_end` not before `period_start`; quarter-end checked at date granularity; report `action` vocabulary `SUBMIT`/`ACKNOWLEDGE`/`RETURN` — implementation/routes/core.py:1500-1501, 1570, implementation/services.py:475-487

Verified: section headers byte-identical to PRD_FINALIZED.md; no new sections; no behavior invented beyond what implementation/ exhibits.

Orchestrator verification: PRD_COMPLETED.md on disk (60,482 bytes, 298 lines); section headers byte-identical to PRD_FINALIZED.md (26 headers, diff empty).
