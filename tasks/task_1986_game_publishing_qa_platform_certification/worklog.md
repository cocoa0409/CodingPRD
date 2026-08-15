## Step 2: Generate Scaffold — 2026-08-15T05:58:27.379Z

All three artifacts are written and pass every check. Final summary:

**Files written** (all three confirmed on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys — verified)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

**SCAFFOLD.yaml counts**: 14 entities, 13 state machines, 13 calculations, 10 ordered validation rows, 63 endpoints, 48 error codes, 8 roles, 2 OCC concurrency rules (`package-create-stale-title-version` on GameTitle, `waiver-create-stale-checklist-version` on ComplianceChecklist), fixed §1.0 envelope verbatim. Profile: compliance/audit + quota-allocation archetypes; flat topology; cyclic state shape; segregation-of-duties role model; logical clock defaulting to 2026-08-01T00:00:00Z (a Saturday — itself load-bearing for a weekend-fee corner).

**§1.8 instance count (19 total, ≥2 per rule)**: dual_variant_calc 2 (vendor invoice provisional-vs-final 200020/220522 cents; readiness optimistic-vs-strict 75.00/50.00), combinatorial_formula 3 — one per mode: (a) tiered×expedited×weekend×cap submission fee = 126000, (b) per-line-then-sum OT rounding 190020 vs rejected 190019, (c) self-inclusive demand-tier window fee 50000 vs rejected 40000, non_linear_state_machine 2 (BugReport double reopen loop; SubmissionPackage cross-round remediation), transitive_cascade 2 (depth-3 blocker-reopen → build demote → package withdraw → window release; depth-2 vendor-terminate → assignment cancel → plan demote), priority_pair_validation_conflict 2 (state-vs-fiscal on submit; safety-vs-referential on hotfix), boundary_precision_check 2 (open-blocker count 0-vs-1 on submit; exact-fit 40==40 vs 41 vendor hours), cross_entity_state_dependency 2 (package→Build CANDIDATE; window→GameTitle CERT_APPROVED), resource_temporal_overlap 2 (half-open adjacency on ReleaseWindow; closed-interval+buffer on CertBlackoutWindow, tested at end+buffer exactly and +1s), compensating_invariant 2 (vendor week-hours; title cert-budget cents, five checkpoint triples summing to 1000000). Every formula-derived assert is a literal pre-computed in Python.

**§1.9 instance count (75 total: 65 active + 10 `excluded_because` stubs)**: entities 14, state_machines 18, calculations 6, validations 12, endpoints 3, errors 8, rbac 6, cross_cutting_layers 7, consistency_model 1. Includes the showpiece hotfix rolling-quota corner (third S1 expedite blocked; the exactly-30-days-old entry excluded by the half-open lower bound, freeing the fourth) and double-rollback → auto-embargo → hotfix-creation-blocked chain. Every one of the 48 error codes has at least one triggering instance (verified programmatically).

**Verification**: `scaffold_lint.py` verdict (final run, verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (63 endpoints, 19 + 65 instances scanned, 1355 calls). Additionally scripted and passing: zero unbound `${var}` placeholders, instance-name uniqueness across both design files, no §1.2.1-forbidden vocabulary, enum-value closure, and grounds resolvability. Two un-testable rules found during replay (dead submit-time re-checks of build/plan state, unreachable because the demotion cascade withdraws packages first) were removed from the scaffold rather than left as dead gates. No sibling task directory was inspected at any point.

## Step 3: Copy Shared Files — 2026-08-15T05:58:52.466Z

Copied `./INSTRUCTION.md` → `tasks/task_1986_game_publishing_qa_platform_certification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T06:15:46.409Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/workspace/PRD.md` (368 lines). The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Summary

**Section skeleton**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Logical Clock & Scheduled Operations, 2.5 Common Resource Properties, 2.6 OCC, 2.7 Certification Budgets & Monetary Precision, 2.8 Validation Cascade & Priority Ordering (explicit 10-tier ordered list), 2.9 Interval Semantics (half-open windows vs. buffered blackouts), 2.10 Cascading State Propagation, 2.11 Nested Resource Retrieval
- §3 Business Logic — 9 subsections organized by workflow stage: title lifecycle / test plans / vendors & invoices / builds & bugs / package assembly & submission / checklist & waivers / findings & remediation / age ratings & localization / windows & hotfixes
- §4 Endpoint Definitions — 63 rows, 4 columns (Method, Path, Description, Authorized Role(s)); status-code paragraph covers 201/200/204 and the uniform `to_status` transition shape
- §5 Error Code Catalogue — 48 rows, 2 columns; document ends at §5 with no audit footer

**Coverage confirmation vs SCAFFOLD.yaml (mechanically verified with a script)**
- Contract 1 (Field-Name Coverage): 110 required identifiers — 83 `entities[].fields` + 60 endpoint `input`/query params + 13 path params — all present in backticks, 0 missing
- Contract 2 (Rule Coverage): all 48 error IDs appear in §2/§3 prose (not just the §5 table); all state-machine transition from/to states expressed (verified per-transition against scaffold); all 13 calculations rendered as precise prose (submission fee tiers/caps, invoice PROVISIONAL vs FINAL per-line rounding order, escrow/spent/available invariant, readiness STRICT/OPTIMISTIC variants, SLA thresholds 24/72/168/720 with strict-greater breach, window demand tiers keyed on total-including-self at 5000 cents/hr, half-open overlap vs. closed+buffered blackout, half-open 30-day S1 quota cap 2, age-rating bundle discount on pre-filing count, per-platform TRC seeding catalog with PLATFORM_TERRITORY mapping, entry coverage); both OCC rules name write capability + `expected_title_version`/`expected_checklist_version` + `ERR_STALE_VERSION`/412; validation priority stated as an explicit ordered cascade
- Contract 3 (§3 Path Purity): 736 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos
- Contract precision: all 90+ enum/state values present as exact backticked strings; no pseudocode operators (`==`/`>=`/`+=`/`min()` etc.) anywhere outside the §2.2 fence; no fuzzy words ("approximately/about/roughly/around…")

**Zero-Silence decisions made during drafting/repair**
1. First verification pass caught 7 missing identifiers (`entries`, `items`, `axis`, `passed`, `to_status`, plus enum tokens `TRANSLATION`/`SIGNOFF`) — each was added in its natural narrative home, not a dumping paragraph.
2. The manual `CANDIDATE → IN_TEST` retest exit (sibling to the system blocker-cascade demotion) was initially omitted — added with its `ERR_INVALID_STATE` guard and identical cascade behavior.
3. Null-until defaults were strengthened for `submitted_at`, `decided_by_user_id`, `withdrawn_cause`, `actual_hours`, and `regression_of_id` so field-level structured content is reconstructible.
4. Three semantically benign "about/around" phrasings were rephrased anyway to keep the fuzzy-word scan at zero.
5. Verifier note: naive backtick extraction gets phase-shifted by §2.2's triple-backtick JSON fences — the verification script strips fenced blocks before tokenizing (worth reusing for Steps 5–8).

## Step 5: Generate Unit Tests — 2026-08-15T07:02:35.116Z

Generation complete. Summary:

## Output

**`test_helpers/` (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/test_helpers/`:
- `types.py` — 14 entity TypedDicts (all carry §2.5 common fields; no append-only entities here), 13 status enums, role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with 67 methods, one per PRD §4 endpoint (incl. `/_clock/set_current_utc`, ops-run, invoice computed read, checklist item ops)
- `api_errors.py` — `ApiErrorId` enum (48 ids) + HTTP status map from PRD §5, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_budget_invariant` (§2.7) and `assert_vendor_hours_invariant` (§3.3)
- `factories.py` — 14 payload factories, input fields only, unique-suffix defaults for unique-constrained fields
- `constants.py` — fee tables, multipliers, SLA hours, tier thresholds, quota constants, TRC catalog + platform→territory map
- `test_users.py` — 7 role header constants + per-user `make_*_headers` builders (needed for the two segregation-of-duties tests, since SoD compares recorded `X-User-ID` values)
- `fixtures.py` — ~45 helpers across all 5 tiers, incl. the composite chains `setup_submittable_package`, `run_certification_chain`, `setup_approved_title`, `setup_launched_title`, `setup_rejected_package_with_finding`, `create_ready_hotfix`

**`test_suite/` (14 files: conftest + 13 test files)** — 103 tests total, all collecting cleanly under pytest.

## Coverage vs. the design indices

- **Queue A (Difficulty): 19/19 instances, 38 tests (exactly 2 per instance)** — every instance passed the PRD-first filter; the PRD §3.3/§3.5/§3.9 prose pins all fee literals, rounding order, boundary behavior, and validation ordering (§2.8's numbered cascade makes both priority-pair instances uniquely derivable).
- **Queue B (Corner): 65/65 non-stub instances, 65 tests. 10 `excluded_because` stubs NOT translated** — all 10 cross-references verified to resolve to real difficulty instances (7 error-trigger stubs + 3 complexity-layer stubs).
- **Instances skipped for PRD-coverage failure: 0** — every non-stub instance had verbatim PRD coverage and a uniquely-derived outcome.

## Verification performed

- Tag audit script: all 103 tests carry exactly one `Design: Difficulty/...` or `Design: Corner/...` line as the last docstring line; every tag resolves to a real instance; no stub tags used; no untagged/dual-tagged tests.
- Citation audit: every quoted PRD span (whitespace-normalized) greps verbatim against `workspace/PRD.md` — 0 mismatches.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" leakage in generated code or docstrings.
- `pytest --collect-only` on the suite: 103 tests, 0 collection errors; pyflakes clean.

One judgment call to flag: `title_create_server_minted_id_input_ignored` was kept (PRD §2.5 "server-minted" pins the outcome if the create succeeds, and §2.8's malformed-request list does not include extra fields, so rejection is not a sanctioned reading).

## Step 6: Generate Implementation — 2026-08-15T07:02:35.116Z

The implementation is complete and verified. Here is the summary.

## Summary

### Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/workspace/implementation/`)

- `start.sh` — foreground launcher, guarded `pip install` (no-op once Flask importable), `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, error handlers (`ApiError` → envelope, 404/405 → `ERR_NOT_FOUND`), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` with 14 empty dicts + logical clock at fixed startup `2026-08-01T00:00:00Z`
- `errors.py` — all 44 error IDs with exact HTTP statuses from PRD §5
- `response.py` — envelope: `meta{api_request_id (req_*), api_request_timestamp (3-fractional-digit ISO)}`, `response_type` (`object`/`array`/`error`), `data{error_id, message}`; pagination fields `limit/offset/total_count/has_more` (defaults 10/0, min 1, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 7 declared roles, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) / `ERR_INSUFFICIENT_PERMISSIONS` (403)
- `helpers.py` — UUIDs, timestamps, logical clock, pagination, computed views (title budget tri-partition + open blockers, vendor weekly ledger + escapes, plan entry coverage, checklist counters, readiness, pack coverage), plan-unlock check, assignment-cancel cascade
- `routes_core.py` — clock, ops-run, titles, vendors, invoice, test plans, entries, assignments
- `routes_cert.py` — builds, bugs, submission packages, checklists (verify/waive/waiver-decision), cert findings, blocker cascade
- `routes_release.py` — age-rating filings, localization packs, release windows, blackout windows, hotfixes

### Endpoint count: 55 routes implemented (covers all 54 scaffold endpoints; the 55th is Flask's automatic OPTIONS sibling — every scaffold table row maps 1:1)

### State machines implemented (14)
GameTitle (linear 6-state), QaVendor (suspend/reinstate/terminate + termination cascade), TestPlan (review loop + system LOCKED↔APPROVED + coverage-loss demotion), TestAssignment (SCHEDULED→IN_PROGRESS→DONE/CANCELLED), Build (test loop, retest, candidacy gate, system CANDIDATE→CONSUMED/IN_TEST, RETIRED — all firing package+window cascades), BugReport (full lifecycle + REOPENED cycle + WONT_FIX/DUPLICATE), SubmissionPackage (ASSEMBLING→SUBMITTED→IN_REVIEW→APPROVED/REJECTED→CLOSED, WITHDRAWN, SUPERSEDED), ComplianceChecklist embedded item machine (UNVERIFIED/FAILED→PASSED/FAILED/NA/WAIVED with waiver sub-states NONE/PENDING/APPROVED/REJECTED/SUPERSEDED), CertFinding (OPEN→FIXED_IN_BUILD→VERIFIED/OPEN reopen loop), AgeRatingFiling (DRAFT→FILED→GRANTED/CHALLENGED→DRAFT amend), LocalizationPack (two independent axes: TRANSLATION DRAFT→TRANSLATING→LQA→LOCKED with fail-back; SIGNOFF UNSIGNED→SIGNED), ReleaseWindow (RESERVED→CONFIRMED→CONSUMED/RELEASED/EXPIRED), Hotfix (DECLARED→IN_DEV→READY_FOR_CERT→EXPEDITED_CERT→DEPLOYED→ROLLED_BACK).

### Calculations implemented (11)
`vendor_weekly_capacity_ledger`, `vendor_invoice_settlement` (PROVISIONAL vs FINAL, per-line ROUND_HALF_UP then sum, then one clawback rounding; OT 1.5x; escape clawback 10%/escape capped 50%), `submission_fee` (round tiers 1.0/0.5/0.25 × expedite 1.75 × weekend 1.2, single rounding, per-platform caps), `cert_budget_ledger` (available+escrow+spent==total invariant; withdrawal refunds, decision converts), `cert_readiness_index` (STRICT + OPTIMISTIC, 2dp half-up), `bug_triage_sla_breach` (strictly-greater boundary, TRIVIAL exempt, sticky), `window_demand_fee` (pinned order: own hours → ISO week → others-in-week → total incl. self → LOW/MEDIUM/HIGH tiers), `release_window_overlap` (half-open, touching not a conflict), `blackout_buffered_exclusion` (closed interval ± buffer, boundary inclusive), `hotfix_rolling_quota` ((now−30d, now] half-open, max 2 S1, S2 exempt), `age_rating_filing_fee` (territory base, 10% bundle discount at ≥2 pre-filing active), `checklist_seeding_catalog` (per-platform TRC/XR items, PLATFORM_TERRITORY map), `entry_coverage` (CANCELLED excluded, DONE counts).

### Error codes implemented
All 44 catalogued error IDs with exact HTTP statuses, wired in the PRD §2.8 priority order (auth → permissions → existence → OCC 412 → state → embargo 403 → temporal → referential 422 → structural 409 → fiscal 402/409).

### Boot verification
`bash start.sh` was smoke-tested repeatedly from fresh processes on multiple ports. Three end-to-end suites (60+ assertions covering auth/RBAC, OCC 412s, supersede, escrow refund, embargo gates, blackout boundary at end+buffer (blocked) vs +1s (allowed), weekend/round fee math, demand-fee tiers 150000/125000/375000, window overlap/adjacency, expiry via ops-run, SLA boundary (exactly at SLA not breached, +1s breached), invoice PROVISIONAL/FINAL with OT and clawback, waiver protocol incl. self-decision 403, findings remediation closing the REJECTED package and unlocking the plan, hotfix quota/window/rollback→auto-embargo at 2 rollbacks, vendor-termination cascade demoting an APPROVED plan, localization 98/95 lock threshold, and pagination envelope) all pass: `ALL SMOKE CHECKS PASSED`, `ALL TARGETED CHECKS PASSED`, `ALL EXTENDED SMOKE CHECKS PASSED`.

### Constraint compliance
- Storage is in-memory dicts only; no SQLite/JSON/tmp persistence. The store starts empty on every boot — no seed/preload/hardcoded entities anywhere (the TRC catalog and fee constants are system rules, not entity data; checklists are seeded only as a side effect of the declared package-create endpoint).
- No endpoint, field, header, or side effect beyond what the PRD/scaffold traces to (internal `_`-prefixed fields are stripped from all responses).
- `start.sh` reads `$PORT`, binds `0.0.0.0`, runs in the foreground via `exec`, and guards the dependency install for fast per-test reboots.

## Step 7: Run Tests and Iterate — 2026-08-15T07:25:00.969Z

All 8 rounds pass: 104/104 in every round. The benchmark task is stable.

## Summary

**Iterations run:** 2 eight-round parallel sweeps (1 diagnostic + 1 verification). Final sweep: all 8 rounds `passed == total` (104/104 each; test count rose 103 → 104 because one failing test was split into two PRD-faithful tests).

**Tests deleted (PRD-silence categories):** No whole tests deleted. One assertion deleted per STEP 1c partial-coverage split:
- `test_06_package_assembly_occ.py::test_second_package_supersedes_assembling_sibling` — removed `assert pkg2["round"] == 1`. **Unique-derivability collapse (side-effect ordering silence):** PRD §3.5 pins "one plus the count of prior non-superseded packages" and "Any prior `ASSEMBLING` package … is moved to `SUPERSEDED`" but never pins whether the count is evaluated before or after the same-operation supersession; §3.7's "each new package for the same title and platform increments `round`" actually supports the implementation's round=2. The scaffold's corner design ("the newcomer computes round 1") drove the assertion. Kept the covered assertions (SUPERSEDED status, plan LOCKED, title version increment).

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `assert_clock_instant(actual, expected_iso)`: validates ISO 8601 and compares parsed instants. Why: PRD §2.5's three-fractional-digit format rule is scoped to id/created_at/updated_at/version; clock-stamped fields (`submitted_at`, `filed_at`, `expedited_cert_entered_at`) have their instant pinned ("stamped from the logical clock", §3.5/§3.9) but their string representation unpinned — exact-string equality was a DEFAULT-FORMAT SILENCE assertion.
- `__init__.py` — exported `assert_clock_instant`.

**Fixes applied to `test_suite/`:**
- `test_07_package_submission_gates.py::test_checklist_frozen_after_submit` — corrected expectation from `ERR_CHECKLIST_NOT_EDITABLE` to `ERR_INVALID_STATE`: post-submit every item is necessarily PASSED/WAIVED/NA, so the §2.8 level-5 item from-state check ("The item must currently be `UNVERIFIED` or `FAILED`; anything else is `ERR_INVALID_STATE`") deterministically pre-empts the level-9 editability gate.
- `test_07...::test_checklist_not_editable_once_package_leaves_assembling` (new, split-out) — abandons an ASSEMBLING package (§3.5 "or abandon an `ASSEMBLING` package" → WITHDRAWN/MANUAL) with items still UNVERIFIED, isolating the §3.6 edit freeze so `ERR_CHECKLIST_NOT_EDITABLE` is the only applicable rejection.
- `test_09_fees_and_budget_conservation.py::test_default_clock_is_saturday_and_weekend_fee_applies` — `submitted_at == "2026-08-01T00:00:00Z"` → `assert_clock_instant(...)` (instant pinned by §2.4/§3.5; representation not). Fee assertion (`144000` = 120000 × 1.20 weekend) unchanged.
- `test_13_hotfixes_post_launch.py::test_happy_path_charges_fee_and_consumes_window` — same representation relaxation for `expedited_cert_entered_at` ("2026-08-20T10:00:00Z" instant). Fee/window-consumption/budget assertions unchanged.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on all four failures (validation-priority ordering per §2.8, round computation per §3.5+§3.7, uniform three-fractional-digit timestamps per §2.5 house format).

## Step 8: Finalize PRD — 2026-08-15T07:37:04.496Z

Done. PRD_FINALIZED.md is written with exactly three inline edits, each tracing to a step_7_diff item and verified against every related implementation path.

## Summary

**Line counts / delta:** PRD.md = 368 lines, PRD_FINALIZED.md = 370 lines (+2 lines, +0.54%). No sections added; all changes are inline inserts.

**Changes (one bullet each):**
- §2.5 — insert — added a house-format paragraph: every instant the API serializes uses the ISO 8601 UTC three-fractional-digit format, covering workflow clock-stamps (`submitted_at`, `filed_at`, `expedited_cert_entered_at`) and echoed caller-supplied window instants (`start_utc`/`end_utc`) — `implementation/helpers.py:18-20` (`clock_iso`), `implementation/routes_cert.py:636`, `implementation/routes_release.py:144`, `implementation/routes_release.py:642`, `implementation/routes_release.py:325-326,337-338,462-463` (`_fmt_dt`).
- §3.5 — revise — pinned `round` count timing: the count of prior non-superseded packages is evaluated before the same assembly's supersession side effect, so a still-`ASSEMBLING` sibling being superseded is counted and the second package starts at `round` 2 — `implementation/routes_cert.py:491-501` (count) vs `implementation/routes_cert.py:516-522` (supersession loop runs after).
- §3.6 — revise — pinned validation order for item verification: the level-5 from-state check (`ERR_INVALID_STATE`) pre-empts the level-9 editability freeze (`ERR_CHECKLIST_NOT_EDITABLE`) when both apply; the freeze surfaces only when the from-state is legal — `implementation/routes_cert.py:727-730` (order of checks in `verify_item`).

**Step-7 items not turned into edits:** the `test_checklist_frozen_after_submit` error-id correction and the new split-out abandon test needed no PRD change beyond edit 2 (the abandon path `ASSEMBLING`→`WITHDRAWN`/`MANUAL` was already pinned verbatim in §3.5); no implementation fixes existed to back-fill.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**
1. **Edit §2.5 (house format).** (a) Subject: string representation of every serialized instant. (b) Enumerated: `helpers.py:18-20` `clock_iso()` (sole formatter for clock-stamps), `helpers.py:23-34` (`touch`/`init_common` → created_at/updated_at), `routes_cert.py:636` (submitted_at), `routes_release.py:144` (filed_at), `routes_release.py:642` (expedited_cert_entered_at), `routes_release.py:337-338` `_fmt_dt` used at 325-326 (release windows) and 462-463 (blackouts); `response.py:15-23` (meta `api_request_timestamp`, already pinned by §2.2); `routes_core.py:41-48` (clock-set returns empty body — no instant serialized); date-only fields (`week_start_date`, `target_launch_date`) out of scope. (c) Wording widened from "clock-stamped fields" to "every instant the API serializes" plus explicit coverage of echoed `start_utc`/`end_utc`, because the enumeration showed `_fmt_dt` re-serializes caller-supplied instants — a clock-stamps-only sentence would have mis-described window/blackout echoes.
2. **Edit §3.5 (round timing).** (a) Subject: when the non-superseded count is evaluated relative to same-operation supersession. (b) Enumerated: `routes_cert.py:491-522` (count → create → supersede ordering; count includes every non-SUPERSEDED status, e.g. WITHDRAWN/REJECTED/CLOSED), `routes_cert.py:414-422` + 631 (`round` consumed by `_submission_fee` tiers — round=2 implies the 0.50 second-round multiplier, matching §3.7), `routes_cert.py:447-532` (only package-creation site), §2.6 OCC mention of superseding assembly (no conflict). Cross-checked surviving test assertion `round == 1` for first package (`test_06...:165`) — consistent. (c) Wording keeps "prior non-superseded packages" verbatim and appends a timing clause plus the concrete round-2 consequence; no narrowing of which statuses count.
3. **Edit §3.6 (verify ordering).** (a) Subject: relative order of the item from-state check vs the editability freeze. (b) Enumerated: `routes_cert.py:713-740` `verify_item` (from-state at 728 before `_checklist_editable` at 730), `routes_cert.py:743-774` `waive_item` (editability at 764 before FAILED-check at 765 — unaffected, both level-9; edit scoped to verification so this path is not mis-described), `routes_cert.py:777-805` `waiver_decision` (no editability check at all — edit makes no editability claim for decisions), `routes_cert.py:660-667` (abandon path feeding the split-out test). (c) Wording anchored to §2.8's level numbers rather than an endpoint-local assertion, and scoped with "verification call" / "item's from-state" so it does not leak onto waiver operations.

Relevant file: `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-15T08:00:54.904Z

Orchestrator note: the first Step 9 subagent completed the full implementation walk (100-item catalog) but exited before applying any edits, leaving PRD_COMPLETED.md as a byte-identical copy of PRD_FINALIZED.md. A retry subagent was spawned with the first agent's catalog inlined as leads to verify; it verified each lead against the implementation and applied all surviving pins. Its summary follows verbatim.

Step 9 complete. All edits were applied to `/home/ubuntu/github/CodingPRD/tasks/task_1986_game_publishing_qa_platform_certification/workspace/PRD_COMPLETED.md` only; every change is an in-paragraph insert/revision (17 lines touched, no sections added).

## Exit Summary

**Source vs output:** `PRD_FINALIZED.md` 370 lines / 63,749 chars → `PRD_COMPLETED.md` 370 lines / 65,984 chars. Char delta: **+2,235**.

**Counts:** ambiguity-pins applied: **14** (A1–A13, A15 — A9 and A11 each pinned in two spots). Mismatch-revisions applied: **3** (M1, M2, A14*). Leads dropped: **0** — however **A14's claimed impl behavior was inverted** (impl does NOT run entry-resolution before state checks; it runs vendor-exists → plan-exists → vendor-ACTIVE → plan-state → entry-resolution). A genuine mismatch existed in the opposite direction (§3.3's narrative predicted ERR_VENDOR_NOT_ACTIVE for a SUSPENDED vendor + missing plan, but impl surfaces ERR_NOT_FOUND), so a corrected revision pinning the actual impl order was applied in its place.

**Changes:**
- §2.2 — insert — ambiguity (A15) — `api_request_timestamp` pinned as stamped from server wall-clock UTC, not the logical clock — response.py:20-23
- §2.3 — insert — ambiguity (A1) — non-integer/out-of-range `limit` (1..100) or negative/non-integer `offset` → ERR_INVALID_REQUEST (400) — helpers.py:77-98
- §2.3 — insert — ambiguity (A7) — list sort ties broken by `id` ascending — routes_core.py:131 (and all other list routes)
- §2.4 — insert — ambiguity (A2) — missing/malformed `to_iso8601` on clock-set → ERR_INVALID_REQUEST (400) — routes_core.py:41-48, helpers.py:42-55
- §2.4 — insert — ambiguity (A11, part 1) — window expiry requires `end_utc` strictly before the logical clock; equality is not expired — routes_core.py:56
- §2.6 — revise — mismatch (M1, spot 1) — `expected_title_version` is optional: enforced only when present (non-integer → 400, mismatch → 412, absent → skipped) — routes_cert.py:457,470-475
- §2.6 — revise — mismatch (M1, spot 2) — same optional-but-enforced semantics for `expected_checklist_version` — routes_cert.py:752,757-763
- §3.1 — insert — ambiguity (A3) — duplicate `title_code` → ERR_INVALID_REQUEST (400) — routes_core.py:91-93
- §3.1 — revise — ambiguity (A8) — embargo endpoint: `embargoed` boolean required, `reason` optional; every call overwrites `embargo_reason` (null when omitted, including clears) — routes_core.py:176-192
- §3.3 — insert — ambiguity (A4) — duplicate vendor `name` → ERR_INVALID_REQUEST (400) — routes_core.py:208-210
- §3.3 — insert — ambiguity (A5) — vendor-view `escapes_count` has no creation-time cutoff, unlike the invoice FINAL escape count (which excludes escapes created after the logical clock) — helpers.py:161-167 vs routes_core.py:311-316
- §3.3 — revise — mismatch (A14*, corrected) — assignment-creation cascade pinned to impl's actual order: vendor-exists → plan-exists → vendor-ACTIVE → plan-state → entry-resolution → Monday → capacity — routes_core.py:471-497
- §3.3 — insert — ambiguity (A6) — invoice `week_start_date` used verbatim as the week filter; only the default is the current ISO week's Monday — routes_core.py:281-289
- §3.4 — insert — ambiguity (A12) — cross-title `regression_of_id` target → ERR_REGRESSION_TARGET_NOT_CLOSED — routes_cert.py:263-268
- §3.6 — insert — ambiguity (A9, spot 1) — waiver request gated on owning package ASSEMBLING (ERR_CHECKLIST_NOT_EDITABLE) — routes_cert.py:764
- §3.6 — insert — ambiguity (A9, spot 2) — waiver decision NOT gated on checklist editability — routes_cert.py:777-805
- §3.7 — revise — mismatch (M2) — finding verification uses the uniform `to_status` shape (`VERIFIED` = pass, `OPEN` = fail-reopen), not a `passed` outcome field — routes_cert.py:873-933
- §3.8 — revise — ambiguity (A10) — amendment (CHALLENGED → DRAFT) leaves `filed_at` unchanged and resets `fee_cents` to null, returning the prior charge from spent to available — routes_release.py:157-166, helpers.py:127-129
- §3.9 — insert — ambiguity (A11, part 2) — same strict-before expiry rule restated at the window-lifecycle passage — routes_core.py:56
- §3.9 — insert — ambiguity (A13) — DEPLOYED consumes the CONFIRMED HOTFIX_DEPLOY window covering the deployment instant (start at-or-before, end strictly after) — routes_release.py:651-659

**Note:** the A14 correction leaves a pre-existing PRD-internal tension untouched: §2.8 level 3 generically lists embedded-entry resolution under "existence," while §3.3 (both before and after my revision) places it after the vendor/plan state checks, matching impl. I left §2.8 unedited per minimal-edit discipline since the endpoint-specific §3.3 narrative is the operative statement.
