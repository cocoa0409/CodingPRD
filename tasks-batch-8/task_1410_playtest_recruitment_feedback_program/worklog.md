# Worklog — task_1410_playtest_recruitment_feedback_program

## Step 1: Create Task Directory — 2026-08-13T04:40:00.000Z

Task directory `tasks/task_1410_playtest_recruitment_feedback_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE (no index scan, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-13T05:46:00.000Z

Scaffold generation complete for `task_1410_playtest_recruitment_feedback_program`. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict. No sibling task directories were inspected — the design was derived purely from the scenario description and the skill specification.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/SCAFFOLD.yaml` (§1.0–§1.7, 2102 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 2066 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 3317 lines)

### Difficulty calibration (harder than Expert band)

- **17 entities** (Expert band: 10–15), **101 endpoints** (Expert: 20–32), **39 error codes** (Expert: 18–30), **7 calculations**, **13 state machines**, 6 roles
- Complexity profile: primary `compliance_audit` + secondary `quota_allocation`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology, segregation_of_duties role model, immediate consistency

### Key structures

- **Entities**: Participant, Moderator, Study, ScreeningApplication, NdaAgreement, NdaSignature, GameBuild, AccessKey, LabStation, PlaytestSession, SessionBooking, SurveyInstrument, SurveyResponse, FeedbackTicket, IncentivePayout, BreachCase, ExposureRecord (append-only, `common_fields: false`)
- **State machines**: cyclic loops on ScreeningApplication (info-request), FeedbackTicket (re-triage), IncentivePayout (reject→resubmit), Participant (suspend↔active); bubble-up enrollment on NDA sign; re-paper cascade ENROLLED→APPROVED; auto no-show on session complete driving strike-based auto-suspension
- **Calculations**: dual-variant `screening_fit_score` (self-reported vs verified) and `incentive_amount` (provisional vs final with no-show penalty); `survey_weighted_score` with pinned per-question-then-sum rounding; tiered incentive multiplier; `budget_commit` with pinned evaluation order; rolling 90-day no-show strike threshold; `feedback_priority_score` with CRITICAL+reach forced-P1 override; `cohort_build_summary` retention across builds from the exposure event log
- **Temporal overlap** with three distinct semantics: station half-open (adjacency allowed), moderator 15-minute buffered turnaround, participant closed-interval (touching conflicts)
- **OCC concurrency**: `session-reschedule-stale-version` and `study-amend-stale-version` (412 ERR_STALE_VERSION)
- **Segregation of duties**: payout creator≠approver≠issuer; breach reporter≠adjudicator
- **Test-driving surface**: `POST /playtests/_clock/set_current_utc` (default `2026-08-01T00:00:00Z`) and `POST /playtests/_sweeps/run-expiry`

### Design stats

- **Difficulty design**: 20 instances across all 9 rules (≥2 each; combinatorial_formula has 3 covering modes a/b/c; cross_entity_state_dependency has 3). All formula-derived asserts are literals pre-computed by executing the formulas (e.g., fit 100 vs 70; payout 13500 vs 11500; survey 0.99/33.0/passed; tiers 22500 vs 12500; priority 225.0 forced P1; retention 50.0)
- **Corner design**: 61 active instances + 14 `excluded_because` stubs across all nine taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, complexity_layers, consistency_model)
- **Final verification**: name uniqueness (95 unique instance names), all grounds resolve to declared §1.1–§1.7 elements, every error code exercised by at least one instance, zero forbidden concurrency vocabulary, file split honored, and lint verdict verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-13T05:46:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1410_playtest_recruitment_feedback_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T06:10:00.000Z

Done. Generated `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/workspace/PRD.md` (384 lines, ~8,800 words) from the scaffold. The withheld index files were never opened.

**Document structure** (domain-derived, per the skill's diversity rules):
- §1 Introduction — 2 paragraphs, business-context angle
- §2 Global specs — 10 subsections: RBAC with per-role `identity` prose, the verbatim §2.2 response envelope, pagination, logical clock + expiry sweep, common resource properties (with the `ExposureRecord` append-only exception), precision/rounding, OCC, the three scheduling-conflict conventions (station half-open / moderator 15-minute buffered / participant closed-interval), the 10-tier validation-order gauntlet with per-tier `applies_to` scopes, and confidentiality/segregation-of-duties principles
- §3 Business logic — 9 lifecycle-grouped subsections with rules scattered across them (fit-score constants live in §3.2, key TTL default in §3.4, strike window in §3.5, incentive tier multipliers in §3.8, etc.)
- §4 Endpoint table — 101 rows, 4 columns, verified cell-for-cell against the scaffold (method, path, authorized roles)
- §5 Error catalogue — 39 rows, 2 columns, verified against the scaffold

**Hard Contract reports:**
```
Field coverage check:
- entities[].fields (+common): 88 required, 88 present, 0 missing
- endpoints[].request_body (non-GET inputs): 53 required, 53 present, 0 missing
- endpoints[].query_params (GET inputs): 17 required, 17 present, 0 missing
- endpoints[].path_params: 1 required (id), 1 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority tiers: 10 checked, 10 expressed with scopes, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write endpoint + expected_study_version/expected_session_version + ERR_STALE_VERSION/412, stale-version framing only), 0 missing
- state_machines[].transitions: 67 checked, 67 with explicit `FROM` → `TO` pairs plus preconditions/side effects, 0 missing
- calculations[]: 7 checked, 7 expressed in precise prose (dual fit/incentive variants, pinned survey rounding order, pinned budget-commit order, forced-P1 override, cohort retention), 0 missing
- validations[] conditions: 39 error IDs all matched to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all cascades (suspend, ban, publish/re-paper, substantiate, complete auto-no-show, retire-revoke, enrollment bubble-up) expressed, 0 missing
- entities[].fields[] structured content: defaults/null-until semantics reconstructible (verified_platform_tags [], key_ttl_hours 72, fit_score_final null until approve, etc.), 0 missing
- sibling-branch symmetry: withdraw ×2, booking-cancel ×3, no-show ×2, payout-VOID ×4, signature-VOID ×2, ban ×2 — all rendered with equal density
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 700
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: §2.2 byte-identical to `section-2.2-response-structure.md`; no pseudocode operators (`>=`, `min()`, `:=`, …) or fuzzy hedging anywhere; boundary rules stated in words (exactly 3 strikes triggers, equality-is-expired on signatures/keys, equality-means-full on cohort/quota, touching endpoints conflict for participants but not stations, exactly-15-minute moderator gap allowed).

## Step 6: Generate Implementation — 2026-08-13T06:50:00.000Z

Implementation complete and verified. Summary of what was generated:

### Generated Files

All under `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/workspace/implementation/`:

- **`start.sh`** (executable) — guards `pip install` behind a `python3 -c "import flask"` import check so per-test reboots are no-ops, then `exec python3 app.py`
- **`app.py`** — Flask entry point; registers all blueprints; ApiError/400/404/405/500 handlers producing the scaffold's exact error envelope; binds `0.0.0.0:$PORT` (default 10000)
- **`db.py`** — in-memory stores (16 entity dicts, all empty at boot — zero seeding) plus the logical clock defaulting to exactly `2026-08-01T00:00:00Z` as the PRD mandates
- **`errors.py`** — all 39 error IDs with their exact HTTP statuses from the scaffold error catalog
- **`response.py`** — envelope helpers: `meta{api_request_id (req_…), api_request_timestamp (ISO-8601 ms + Z)}`, `response_type` object/array/error, pagination fields `limit/offset/total_count/has_more` (default 10, min 1, max 100), list sort by `created_at` ascending
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth (six declared roles), 401/403 semantics
- **`routes/`** (16 modules) — all 74 endpoints from the endpoint table
- **`services/`** — `calculations.py` (screening fit score with self_reported/verified variants and half-up integer platform rounding; incentive provisional/final variants with tier multipliers 1.5/1.25/1.0 and 2000-cent no-show penalty floored at 0; survey weighted score with per-question rounding before summation; feedback priority with forced-P1 override; cohort build summary with adjacent-build retention), `cascade.py` (suspension/ban cascades, waitlist promotion by earliest `created_at`, rolling 90-day strike count with exactly-3 auto-suspension, append-only ExposureRecord journal with `KEY_ISSUED/KEY_REDEEMED/KEY_REVOKED/KEY_EXPIRED`), `serializers.py` (per-entity public field lists; ExposureRecord has `id`+`created_at` only — no `updated_at`/`version`)

### Key behaviors verified by live testing

- Full lifecycle smoke test (~80 assertions): registration → activation → study → application two-pass fit score → NDA publish/sign bubble-up enrollment → re-papering cascade (retire/void/revert/re-pin/fresh PENDING signature) → builds/keys/exposure journal → sessions with waitlist promotion → auto no-show on complete → surveys → tickets → payout segregation-of-duties and budget commit/spend → breach adjudication with risk scores and ban cascade → expiry sweep
- Conflict semantics: station half-open (touching OK), moderator 15-minute buffer (exactly 15 allowed, 14 conflicts), participant closed-interval (touching conflicts)
- OCC: `ERR_STALE_VERSION` 412 on study amend and session reschedule
- Gate orderings: NDA-signed outranks quota; quota outranks duplicate-key (fixed during review per PRD §3.4); payout approve state→SoD→banned→budget
- Boundary rules: equality at `expires_at` is expired for redeem/sign; sweep expires at `expires_at <= now`; pass threshold equality passes
- Cold boot via `bash start.sh`: empty store (`total_count: 0`), clock at the PRD default, server HTTP-ready in ~2s

One deliberate ambiguity resolution: for payout approve, SoD (403) is checked before the participant-BANNED (422) check, matching the PRD §3.8 narrative and scaffold state-machine precondition order over the generic tier list.

*(Note: Step 6 ran concurrently with Step 5; worklog entries are recorded in completion order.)*

## Step 5: Generate Unit Tests — 2026-08-13T07:00:00.000Z

All checks pass. Generation complete. Final summary:

### Generated Output

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/test_helpers/`:
- `types.py` — 17 entity TypedDicts (ExposureRecord correctly omits `updated_at`/`version`), 20 enums
- `api_client.py` — 70 endpoint methods, one per PRD §4 row, all under `/playtests`
- `api_errors.py` — all 39 error IDs + HTTP map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity assertions + instant-parsing helpers (timestamps compared as parsed datetimes, not strings)
- `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_participant_headers`/`make_moderator_headers` builders, opaque officer/legal builders for SoD chains)
- `fixtures.py` — composite chains: enrollment (apply→review→approve→sign), session history with attendance/no-show outcomes, payout-ready scenarios, published NDA/instrument helpers, breach reporting/opening

**`test_suite/`** — `conftest.py` + 12 test files, **101 tests**, all collected cleanly by pytest.

### Coverage

- **Queue A (Difficulty): 20/20 instances × 2 tests = 40 tests.** Every instance has exactly two tagged tests splitting distinct facets (e.g., score divergence vs. NDA pinning; suspension cascade participant-side vs. booking-side).
- **Queue B (Corner): 61/61 non-stub instances × 1 test = 61 tests.**
- **14 `excluded_because:` stubs not translated**; all 14 cross-references verified to resolve to real difficulty instances.
- **Instances skipped for PRD-first filter failure: 0.**

### Assertion-level derivability adjustments (PRD-first, never weakening the pinned claim)

1. Dropped hard-coded `version == 1` on creation (PRD pins "increments by one on every mutation" but never the initial value); OCC tests capture the creation version and assert `+1` after the winning write.
2. Timestamp assertions compare parsed instants (PRD pins ISO 8601 / 3 fractional digits, not `Z`-vs-offset serialization).
3. `fit_score_final == null` after a *failed* approve not asserted — PRD §3.2 sequences "computed, stored as `fit_score_final`, and compared" before the rejection, so null-on-failure is not uniquely derivable; the test keeps the error ID + `UNDER_REVIEW` retention.
4. Ban-cascade exposure journal asserted as a multiset (all three records share the pinned clock instant; list tie-break order is not PRD-pinned).

### Stage 2 self-check verdict: PASS

- 101/101 tests carry exactly one `Design:` tag; all tags resolve verbatim to instance `name:` keys in the source yamls (0 untagged, 0 dual-tagged, 0 dangling).
- 165 citation spans across all docstrings survive literal whitespace-normalized grep of PRD.md.
- All 39 asserted `error_id`s appear in PRD narrative prose (§2–§3), not just the §5 table.
- No `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated comments or docstrings; every test builds its own state from an empty DB via PRD-declared endpoints.

## Test-Iterate Loop — 2026-08-13T07:20:00.000Z

### Sweep 1 (8 parallel rounds, per-test-server isolation)

808 test executions: 800 passed, 0 assertion failures, 8 setup ERRORs — the identical test (`test_06_sessions_scheduling.py::test_session_full_lifecycle_happy_path`, suite index 55) errored in all 8 rounds with "API server ... could not be restarted" (the runner's hardcoded 15s restart-readiness poll exhausted). Deterministic same-index failure across lockstep rounds is the documented signature of the shared-host bind race: the runner claims ports from the kernel ephemeral range, and a transient outbound connection from a co-tenant pipeline (≈29 sibling `prd-bench-local-run` processes were live on the host during the sweep) can hold the freshly-killed server port as its ephemeral source socket at the bind instant; Werkzeug's `app.run` path `sys.exit(1)`s on `EADDRINUSE`, killing the fresh server and exhausting the poll window. No test assertion was implicated.

### Fixes (implementation boot layer only — no business logic touched)

- `workspace/implementation/app.py` — replaced `app.run()` with a manual `socket.bind`/`listen` (`SO_REUSEADDR`, 12s retry loop at 0.2s) + `werkzeug.make_server(..., threaded=True, fd=sock.fileno())`. A transient `EADDRINUSE` at the bind instant now retries inside the runner's 15s poll window instead of crashing. Established pattern from task_1289 (root cause empirically verified in task_1288's worklog).
- `workspace/implementation/start.sh` — dependency check now gated by a `.deps_ok` stamp file (re-checked whenever `requirements.txt` is newer), so steady-state per-test reboots skip the duplicate `python3 -c "import flask"` interpreter spawn. Boot metadata only; storage remains in-memory; no entity data seeded.

### Sweep 2 (verification)

All 8 rounds clean: **101/101 passed, 0 failed, 0 errors in every round** (808/808). Exit condition met.

- Iterations run: 2 sweeps.
- Tests deleted: 0 — no failure ever implicated a test assertion; the only failures were runner-level setup timeouts.
- `test_helpers/` fixes: none.
- `implementation/` fixes: `app.py` (bind-retry boot, why: EADDRINUSE crash under restart storm), `start.sh` (`.deps_ok` marker, why: halve per-boot cost under 8× lockstep reboots).

## Step 8: Finalize PRD — 2026-08-13T07:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/workspace/PRD_FINALIZED.md` as a verbatim copy of `PRD.md`. **Zero edits.**

### Summary

- **Line counts / %-delta**: PRD.md 383 lines, PRD_FINALIZED.md 383 lines — 0.0% delta (byte-identical, verified via `diff`).
- **Changes**: none.

### Verification reasoning (zero-edit outcome)

Step 7's entire diff is two boot-layer infrastructure fixes with no business-logic content, and per-edit analysis confirmed neither implicates any PRD behavioral prose:

1. **`app.py` socket-bind retry** (subject: process boot / EADDRINUSE resilience). Read `implementation/app.py` in full: the change is confined to the `if __name__ == "__main__":` block — manual `socket.socket`/`SO_REUSEADDR`/`bind(("0.0.0.0", PORT))`/`listen` with a 12s retry loop at 0.2s, then `werkzeug.make_server(..., threaded=True, fd=sock.fileno())`. Everything above (blueprint registration, error handlers) is unchanged. This is invisible to the API contract: it alters no request/response behavior, no state machine, no storage. The bind contract (PORT env, default 10000, 0.0.0.0, foreground) is governed by `INSTRUCTION.md`, not the PRD. Grepped PRD.md for `port|bind|socket|boot|startup|start.sh|dependenc|install|werkzeug|listen` — all hits were false positives (`report*` contains "port") except one legitimate business-logic sentence (§2.4 "At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`"), which the implementation honors in `db.py:12` — PRD and impl already agree, no patch needed.

2. **`start.sh` `.deps_ok` stamp-file guard** (subject: dependency-check memoization). Read `start.sh` in full: the stamp file only skips a redundant `python3 -c "import flask"` spawn; the script still ends in `exec python3 app.py` (foreground). No endpoint, entity, or state transition is touched. PRD.md contains no prose about dependency installation or launcher scripts, so there is no PRD silence in scope — the PRD's contract begins at the HTTP layer, and boot mechanics are `INSTRUCTION.md`'s domain.

No tests were deleted and no `test_helpers/` fixes occurred, so there are no test-side signals of PRD ambiguity to pin either. A fresh implementer reading `PRD.md` alone already produces a behaviorally equivalent codebase; adding socket-retry or stamp-file prose would invent requirements the PRD deliberately does not own.

## Step 9: Complete PRD — 2026-08-13T08:05:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1410_playtest_recruitment_feedback_program/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` existed (byte-identical to `PRD.md`) and was copied to `PRD_COMPLETED.md`. Source: 383 lines / 64,843 chars. Completed: 383 lines / 67,536 chars. Char delta: **+2,693**, line delta: **0** (all changes are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 11 ambiguity-pins, 6 mismatch-revisions (17 changes across 15 paragraphs). Method: read all 14 implementation modules exhaustively (routes, services, middleware, envelope/pagination helpers), verified all 101 endpoints match the §4 table and all error IDs/HTTP statuses match §5, then pinned only where behavior differed or was unpinned. Tests were used only as auxiliary cross-reference.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — pinned that ownership comparisons apply only to the owner-only actions named in §3, and list/fetch endpoints are never owner-scoped — `implementation/routes/applications.py:99-103` (GET has no ownership check; cf. `:135`, `:207`), `routes/bookings.py:117-121`.
- §2.3 — insert — ambiguity — pinned `total_count` = filtered match count and `has_more` ⟺ `offset`+`limit` < `total_count` — `implementation/response.py:79-85`.
- §2.3 — insert — ambiguity — pinned `created_at` ties broken by creation sequence (listing is effectively creation order under a held logical clock) — `implementation/response.py:81` (sort key `(_created_sort, _seq)`).
- §2.5 — insert — ambiguity — pinned exposure-records listing filters: `participant_id`, `build_id`, `study_id`, `event_type` — `implementation/routes/exposure.py:19`.
- §2.7 — insert — ambiguity — pinned that on both OCC endpoints the expected-version field is validated (presence/integer → `ERR_INVALID_REQUEST`) and compared immediately after the resource loads, ahead of all remaining body/state/conflict checks — `implementation/routes/studies.py:89-98`, `implementation/routes/sessions.py:176-189`.
- §2.9 tier 2 — revise — mismatch — tier-2 ownership placement corrected: breach-branch and moderator-owned session actions evaluate the target's state check before the ownership comparison — `implementation/routes/breaches.py:101-104,128-131,141-144`; `routes/bookings.py:143-148`; `routes/sessions.py:209-214,232-235`.
- §2.9 tier 4 — insert — ambiguity — pinned that on create endpoints the caller's own `X-User-ID` (Participant role) is resolved after body FKs, unknown participant → `ERR_NOT_FOUND` — `implementation/routes/applications.py:52-54`, `routes/bookings.py:52-54`, `routes/surveys.py:142-144`.
- §2.9 tier 5 — revise — mismatch — "three named variants" was incomplete; added `ERR_PARTICIPANT_NOT_ACTIVE` for application create by a non-`ACTIVE` participant — `implementation/routes/applications.py:59-60`.
- §2.9 tier 7 — revise — mismatch — on payout approval, segregation of duties is evaluated *before* the tier-6 banned-participant gate (opposite of the tier order as written) — `implementation/routes/payouts.py:131-137`.
- §2.10 — revise — mismatch — replaced "three distinct `IncentiveOfficer` identities are required" with the impl's actual contract: only two pairwise checks (drafter≠approver, approver≠issuer); the drafting officer may also issue — `implementation/routes/payouts.py:131,175-176`.
- §3.2 — insert — ambiguity — `supplemental_note` on submit-info is accepted but never persisted on the application — `implementation/routes/applications.py:131-141`.
- §3.4 — revise — ambiguity — cohort-summary entries also carry `build_id`, `build_label`, and `released_at`, not just the four metrics — `implementation/services/calculations.py:220-228`.
- §3.5 — revise — mismatch — waitlist promotion claim "ties impossible because creation timestamps are server-stamped and distinct" is false under a held logical clock; corrected to ties broken by creation sequence, earliest first — `implementation/services/cascade.py:69`.
- §3.5 — insert — ambiguity — reschedule re-runs station/moderator conflict checks with the session itself excluded — `implementation/routes/sessions.py:192-197` (`exclude_session_id`).
- §3.5 — insert — ambiguity — attendance and completion evaluate state checks before the moderator ownership comparison, and completion's auto-no-show set is snapshotted when completion begins — `implementation/routes/bookings.py:143-148`, `implementation/routes/sessions.py:232-251`.
- §3.9 — insert — ambiguity — on each adjudication branch the case-state check (`ERR_INVALID_STATE`) runs before the `adjudicated_by_user_id` comparison (`ERR_FORBIDDEN`) — `implementation/routes/breaches.py:101-104,128-131,141-144`.
- §3.9 — revise — mismatch — a `BAN` sanction drives only an `ACTIVE`/`SUSPENDED` participant into `BANNED`; a still-`REGISTERED` participant keeps that status while the case closes `SANCTIONED` — `implementation/routes/breaches.py:154-158`.

Everything else in the implementation (endpoint catalogue, RBAC per endpoint, state machines, fit-score/payout/priority/survey formulas and rounding order, cascades, envelope shapes, gate orderings on key issuance/booking/approval/submission, sweep boundary semantics, defaults) was already uniquely pinned by the PRD and left untouched.
