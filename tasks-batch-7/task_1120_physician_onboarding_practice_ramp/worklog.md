# Worklog — task_1120_physician_onboarding_practice_ramp

## Step 1: Create task directory — 2026-08-10T19:20:40.000Z

Output folder pre-assigned as `tasks/task_1120_physician_onboarding_practice_ramp`; directory and `workspace/` subdirectory already exist. Auto-index scan skipped per instructions. Step 1 treated as done.


## Step 2: Generate scaffold artifacts — 2026-08-10T19:45:00.000Z

Generated SCAFFOLD.yaml (§1.0–§1.7: 15 entities, 13 state machines, 7 calculations, 11 validations, 74 endpoints, 62 errors, 9 roles, 2 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8: 9 rules / 19 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9: 48 instances incl. 3 excluded_because stubs). Complexity: workflow_orchestration + graph_constraint; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. scaffold_lint.py: VERDICT clean (811 calls scanned). No sibling task inspected.

## Step 3: Copy shared files — 2026-08-10T20:19:25.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1120_physician_onboarding_practice_ramp/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T20:40:59.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/workspace/PRD.md` (395 lines). The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no other task directory was touched.

**Document structure** (skeleton designed fresh for this domain, not copied from the example):
- §1 Introduction — 2 paragraphs, business-context angle (recruitment investment at risk during the ramp corridor).
- §2 Global Specifications — 11 subsections: RBAC (with per-role `identity` prose: `Physician`/`MentorPhysician` entity-backed, seven opaque roles), verbatim §2.2 envelope, pagination, the logical clock + pinned epoch sweep, common resource properties (incl. the `common_fields: false` exception for CheckIn and RetentionRiskSnapshot), parallel case dimensions and the posture gate, cascading consistency/versioning, OCC, the 11-level validation order, left-to-right identifier resolution, and units/precision/rounding.
- §3 Business Logic — 9 subsections organized along the case timeline (recruiting → offers → credentialing DAG → training → schedule → panel → marketing → guarantee/milestones → mentorship/retention/separation), with all state pairs, cascades, and constants embedded in narrative.
- §4 Endpoint table — 74 rows, exactly 4 columns; §5 Error catalogue — 62 rows, exactly 2 columns.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body/input: 17 required, 17 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing (incl. limit/offset)
- (total deduplicated required set: 101, 0 missing; path param {id} present)
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.9 numbered order + in-rule orderings: state-before-segregation on verify, mentor rules pinned, check-in unique-then-ordered, overlap-before-budget), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (§2.8 names POST /onboarding/offers and POST /onboarding/mentorship-assignments + expected_onboarding_case_version + ERR_STALE_VERSION/412, stale-read framing only), 0 missing
- state_machines[].transitions: 48 checked, 48 fully expressed (from/to states, preconditions with error IDs, side effects incl. all cascades and symmetric sibling branches), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (critical path SLA table + 14-day buffer, weekly minutes per specialty, guarantee draw ACTUAL/PROJECTED with pinned order, attainment threshold, retention risk with per-term rounding pinned, campaign spend ledger, panel census bounds), 0 missing
- validations[] conditions: 62 error IDs checked, 62 matchable to trigger conditions in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 74 checked, 74 expressed (incl. per-endpoint case-version propagation points), 0 missing
- entities[].fields[] structured content: 84 checked, 84 reconstructible (defaults, ranges, enum members, sources all stated), 0 missing
- sibling-branch symmetry: 8 groups checked (withdraw ×4, accept/decline ×2, credential expiry ×5, BLOCKED restore ×4, epoch sweep ×3 phases, mentor checks ×3, guarantee ACTUAL/PROJECTED, snapshot TRAILING/LEADING), 8 symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 711
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks passed: §2.2 byte-identical to the fixed source block (including `req_RANDOMALPHANUM123456` and empty `"data": { }`); no pseudocode operators (`>=`, `==`, `+=`, …) or fuzzy approximators in prose; all enum/state strings from the scaffold present verbatim; endpoint table matches the scaffold's 74 endpoints exactly with no extras. Repairs applied during verification: removed a duplicated `ERR_MILESTONE_NOT_FOUND` row, reworded one ambiguous "around", and broadened §2.7 to enumerate every case-`version` propagation point per the scaffold's endpoint side effects.

## Step 5: Generate unit tests — 2026-08-10T21:16:35.000Z

Done. The complete test infrastructure and suite for `task_1120_physician_onboarding_practice_ramp` is generated and audited.

## What was generated

**`test_helpers/` (Stage 1, 9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/test_helpers/`:
- `types.py` — 14 status/enum types + 15 entity TypedDicts; CheckIn and RetentionRiskSnapshot correctly carry only `id` + `created_at` (common_fields false per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 methods incl. `/_clock/set_current_utc` and `/_ops/run_epoch`)
- `api_errors.py` — all 63 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (SLA days, required weekly minutes per specialty, wRVU curve, RAMP_FILL_CURVE, band thresholds), `test_users.py` (opaque role constants + `make_physician_headers`/`make_mentor_headers`/`make_specialist_headers` for entity-backed and segregation-sensitive calls), `fixtures.py` (executed-offer pipeline, credential approval with cs-1/cs-2 segregation, idempotent `complete_training`, ready schedule, full go-live, active guarantee, report/attest, mentorship), `__init__.py` barrel

**`test_suite/` (Stage 2, 13 files, 83 tests)** — organized by concern: registration/cases, offers/negotiation, credentials, training, schedule/panel, campaigns, guarantee/milestones, mentorship, retention risk, expiry cascade, API conventions, RBAC.

## Audit results (all passing)

- **Coverage**: all 19 difficulty instances have exactly 2 tests (38 total); all 45 non-stub corner instances have ≥1 test (45 total). The 3 `excluded_because:` stubs (cascading_side_effects_chains, dual_variant_calculation_both_domains, rate_threshold_band_boundary) were verified to resolve to real difficulty instances and were not translated.
- **Tags**: every test docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the yaml `name:`; no dual/unknown/stub-pointing tags.
- **Citations**: every PRD quote in every docstring survives a literal grep of `workspace/PRD.md` (whitespace/backtick-normalized); all are rule-bearing sentences (§2.4–§3.9 prose), not endpoint titles.
- **Hygiene**: no `skip`/`skipif`/`xfail`; pyflakes-clean; all 83 tests collect under pytest; no "scaffold" references in comments/docstrings.
- **Numeric derivations independently recomputed from PRD prose**: guarantee draws (800000/920000/200000 → 19200000 projected etc.), retention scores (TRAILING 57.50 / LEADING 63.33 at month offset 3; pinned per-term rounding 11.67+23.63+25.00+14.70 = 75.00 → CRITICAL vs. the 74.99 sum-raw alternative), critical path 90+45+75=210 → earliest start 2026-12-11 from the 2026-05-01 clock default, census/capacity and adjacency boundaries.

No instances were skipped — every design-index instance had verbatim PRD coverage with uniquely derivable outcomes.

## Step 6: Generate implementation — 2026-08-10T21:16:35.000Z

All three smoke suites pass on fresh boots. The implementation is complete.

## What was built

A complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000), foreground.
- **`app.py`** — Flask wiring, `ApiError` handler emitting the PRD §2.2 error envelope.
- **`db.py`** — in-memory store (empty at every boot, no seeding), logical clock defaulting to exactly `2026-05-01T00:00:00Z`, monotonic sequence for stable `created_at` ordering, 3-fractional-digit UTC timestamps, version starting at 1.
- **`errors.py` / `response.py` / `middleware.py`** — full §5 error catalog with exact HTTP statuses; envelope (`meta.api_request_id` with `req_` prefix, `response_type`, `data`); `limit`/`offset` pagination (default 10, clamped 1..100); `X-User-ID`/`X-User-Role` auth against the nine declared roles.
- **`domain.py`** — all scaffold constants (SLA days, weekly-minute requirements per specialty, wRVU/fill curves, weights, caps), recomputes for the three parallel case dimensions + derived `posture` gate, credential DAG critical path, transitive block/lapse/restore cascades, `Decimal`-based guarantee draws (ACTUAL/PROJECTED) with HALF_UP penalty rounding, and the four-component retention risk score with pinned per-component-then-per-term 2dp rounding.
- **`routes/`** — 13 blueprints covering all 49 endpoints, including `/_clock/set_current_utc` and `/_ops/run_epoch` (pinned sweep order: credential expiry cascade → offer expiry → milestone lapse).

## Key fidelity decisions

- Validation ordering follows PRD §2.9: auth → role → ownership (Physician/MentorPhysician entity-backed) → existence (left-to-right, resource-specific 404s) → schema → state → segregation-of-duties (after state on verify) → linked-entity gates → temporal → structural → fiscal.
- OCC (`expected_onboarding_case_version` → `ERR_STALE_VERSION` 412) enforced on offer and mentorship creation.
- Decline skips the expiry check (PRD §3.2 pins only ownership + negotiation-open for it); counter/accept refuse at-or-past `expires_at` while the sweep expires strictly past it.
- Guarantee ledger fields are derived at read time from milestones + stored `total_repaid_cents`, so lapse/attest/reconcile always read consistently.
- Case version increments exactly once per case-touching action per the endpoint table; panel freeze cascades only where specified (credential expiry, template retirement); LEADING risk counts unreported elapsed months (PENDING/REPORTED/LAPSED) as missed among due months.

## Verification

Three smoke suites (run against fresh boots, exercising the full pipeline: registration → case → negotiation with round limit → execution with critical-path gate → credentialing with segregation, reject/restore and expiry cascades → training incl. retakes and template quota → schedule overlap half-open semantics → panel open/freeze/unfreeze/census bounds → campaign budget ledger and event window adjacency → guarantee activation, attestation math, repayments, settlement → mentorship check-in ordering, CRISIS escalation, supersede → TRAILING/LEADING snapshots → separation cascade) all pass. Boot-to-HTTP-ready measured at ~1.1s, and each restart confirmed to start with an empty store.

## Step 7: Run tests and iterate — 2026-08-10T21:25:26.000Z

All 8 rounds pass 83/83. Clean exit.

## Summary

- **Iterations run:** 2 (initial sweep: 81/83 × 8 rounds, two deterministic failures; fix sweep: 83/83 × 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/test_suite/test_03_credentials.py` — `test_file_blocked_until_dependency_approved`: removed a redundant pre-submit of the `STATE_LICENSE` item. The test's setup submitted docs, then the `approve_credential_item` fixture re-submitted, and the PRD-faithful implementation correctly rejected the second submit with `ERR_INVALID_STATE` (PRD §3.3: "A `CredentialingSpecialist` submits documents for an item in `PENDING` or `REJECTED` — submitting from any other state is rejected with `ERR_INVALID_STATE`"). The pre-submit was not load-bearing for the assertion (filing `dea` still fails with `ERR_ITEM_DEPENDENCY_NOT_APPROVED` while `lic` is unapproved, and succeeds after `lic` is approved).

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/workspace/implementation/db.py` — `new_record()`, `new_point_record()`, and `bump()` now stamp `created_at`/`updated_at` from the logical clock (new `clock_ts()` helper using `fmt_ts(store.clock)`) instead of wall time. PRD §2.4 verbatim: "The server maintains a logical clock whose startup default is exactly 2026-05-01T00:00:00Z and which never falls back to wall-clock time." Response-envelope `meta.api_request_timestamp` intentionally left on wall time — PRD §2.2 requires only "a server-generated ISO 8601 UTC timestamp" for meta, and no test asserts otherwise.

(Orchestrator verification: all 8 `results.{1..8}.json` files on disk report passed=83 total=83.)


## Step 8: Finalize PRD — 2026-08-10T21:29:30.000Z

PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1120_physician_onboarding_practice_ramp/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 395 lines; PRD_FINALIZED.md 395 lines (0.0% delta — 3 lines revised inline, none added/removed).

**Step 7 diff item triage:**
- `test_suite/test_03_credentials.py` fix — pure fixture bug, **no PRD edit**. PRD §3.3 already pins verbatim: "A CredentialingSpecialist submits documents for an item in PENDING or REJECTED — submitting from any other state is rejected with ERR_INVALID_STATE", and the implementation (`routes/credentials.py:117-124`) matches. Nothing was silent or mismatched.
- `implementation/db.py` fix — **revealed two PRD silences**, both patched (2 edits below).

**Changes (one bullet per change):**
- §2.2 — revise — `api_request_timestamp` bullet now states it is "taken from wall-clock time; it does not read the logical clock of §2.4" — impl: `implementation/response.py:18` (sole meta producer, uses `now_ts()` = `datetime.now(timezone.utc)`; `implementation/db.py:59-60`).
- §2.5 — revise — `created_at` bullet now reads "stamped from the logical clock of §2.4 — never from wall-clock time — when the resource is created"; `updated_at` bullet now reads "refreshed from the same logical clock on every mutation" — impl: `implementation/db.py:63-66` (`clock_ts()`), `:78-87` (`new_record`), `:90-96` (`new_point_record`), `:99-102` (`bump`).

**Per-edit pre-edit search log:**

Edit 1 (§2.5, created_at/updated_at):
- (a) Subject: source clock for resource `created_at`/`updated_at` stamps.
- (b) Paths enumerated: grep for `created_at|updated_at` writes across all of `implementation/` — the only writers are `db.py:80-86` (`new_record`, used for all 13 primary resources), `db.py:90-96` (`new_point_record`, used for CheckIns at `routes/mentorship.py:140` and Snapshots at `routes/snapshots.py:30`), and `db.py:99-102` (`bump`, the sole `updated_at` refresher). Serializers in `domain.py:623-854` only read. Adjacent timestamp fields checked for wording conflicts: `opened_at` (`routes/panels.py:61`, already pinned to logical clock by PRD §3.6) and `occurred_on` (`routes/mentorship.py:145`, already pinned by §3.9) — wording is scoped strictly to `created_at`/`updated_at`, so no conflict.
- (c) Wording adjustment: revised at the field-definition bullet level rather than adding a separate sentence, so the definition automatically covers the two point-in-time exceptions (CheckIn/RetentionRiskSnapshot), whose `created_at` the exceptions paragraph references and which `new_point_record()` also stamps from `clock_ts()`.

Edit 2 (§2.2, api_request_timestamp):
- (a) Subject: source clock for the response-envelope `meta.api_request_timestamp`.
- (b) Paths enumerated: grep for `api_request_timestamp` across `implementation/` — single producer at `response.py:18` inside `_meta()`, which feeds `success_object`, `success_list`, and `error_body` (every success, list, and error envelope). Also cross-checked `db.py:59-60` (`now_ts` = wall time) and confirmed §2.4's "never falls back to wall-clock time" speaks only about the logical clock itself, so the new clause does not contradict it.
- (c) Wording adjustment: used the permissive phrasing "taken from wall-clock time; it does not read the logical clock of §2.4" rather than a prescriptive format change, keeping the existing "server-generated ISO 8601 UTC timestamp with three fractional digits" requirement intact and consistent with every envelope path (success, list, error).

No other edits were made; all other behavior in `implementation/` traced to the Step 7 diff was already uniquely determined by PRD.md prose.

## Step 9: Complete PRD — 2026-08-10T21:45:00.000Z

PRD_COMPLETED.md is written and verified. Final summary:

## Summary

**Source**: `PRD_FINALIZED.md` (395 lines, 72,317 chars) → `PRD_COMPLETED.md` (395 lines, 75,211 chars). Line count unchanged (all edits are in-paragraph inserts/revisions); char delta **+2,894**. 19 diff hunks across 20 lines.

**Counts**: 17 ambiguity-pins, 6 mismatch-revisions (23 changes total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl anchor):

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_VALIDATION` (400); out-of-range integers clamped into bounds, not rejected — implementation/response.py:72-81
- §2.3 — insert — ambiguity — `created_at` ties (common, logical-clock stamped) broken by insertion order — implementation/response.py:85-90, routes/physicians.py:54
- §2.4 — insert — ambiguity — `to_iso8601` accepts date-only (midnight UTC) and offset-naive datetimes (treated as UTC) — implementation/domain.py:99-115, routes/ops.py:19-20
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:78-87
- §2.8 — insert — ambiguity — stale-version check positioned immediately after case-identifier resolution, before all state/linked-entity/temporal/structural gates — implementation/routes/offers.py:88-93, routes/mentorship.py:36-44
- §2.9 (step 4) — revise — mismatch — creation endpoints parse body schema (presence/type/enum) before resolving body identifiers; §3.3 conditionals/`depends_on` validation and §3.5 range bounds run right after the case resolves — implementation/routes/offers.py:75-90, routes/cases.py:22-27, routes/credentials.py:44-71, routes/templates.py:35-50
- §2.9 (step 5) — insert — mismatch — offer extension and document submission evaluate the state precondition before parsing their all-optional bodies — implementation/routes/offers.py:150-154, routes/credentials.py:122-126
- §3.1 — insert — ambiguity — duplicate email rejected with `ERR_VALIDATION` (400) — implementation/routes/physicians.py:25-27
- §3.1 — insert — ambiguity — case opening requires physician `PROSPECT`; duplicate-case check fires first, case-less non-PROSPECT gets `ERR_INVALID_STATE` (409) — implementation/routes/cases.py:28-31
- §3.2 — insert — ambiguity — `physician_note` (counter/decline) and withdrawal `reason` accepted but not persisted — implementation/routes/offers.py:180-234
- §3.2 — revise — mismatch — amendment also overwrites the guarantee's `start_month` from the new offer — implementation/routes/offers.py:264-266
- §3.3 — revise — mismatch — dropped "the first three of these" phrasing (Medicare is fourth in the enumeration); required types pinned by name — implementation/domain.py:23
- §3.3 — revise — mismatch — `payer_code` "required if and only if" relaxed to "required when" — implementation/routes/credentials.py:54-56
- §3.3 — insert — ambiguity — unresolved dependency id rejected with `ERR_CREDENTIAL_ITEM_NOT_FOUND` (404); `payer_code`/`expires_on` may be supplied and are stored on non-requiring types — implementation/routes/credentials.py:47-48, 68-71
- §3.3 — insert — ambiguity — `verification_note` and `filing_ref` accepted but not persisted (bodies never read) — implementation/routes/credentials.py:135-166
- §3.4 — insert — ambiguity — duplicate `module_code` within a plan rejected with `ERR_VALIDATION` (400) — implementation/routes/training.py:98-101
- §3.4 — insert — ambiguity — `scheduled_on` optional, defaults to current logical date — implementation/routes/training.py:145-153
- §3.4 — insert — ambiguity — omitted `templates_built_count` counts as zero for the gate; `score` is recorded before the gate, so a rejected completion leaves score on the still-`SCHEDULED` module — implementation/routes/training.py:185-191
- §3.8 — insert — ambiguity — term months beyond twelve repeat the twelfth wRVU target (500) — implementation/routes/offers.py:323
- §3.9 — revise — mismatch — LEADING `milestone_risk` numerator counts every due month not attested-as-attained (missed attested, `LAPSED`, and due `PENDING`/`REPORTED` all count), not "missed attested plus unreconciled" — implementation/domain.py:528-543
- §3.9 — insert — ambiguity — fill-curve lookups clamp at the twelfth point (85%) for offsets beyond twelve, both variants — implementation/domain.py:553-555
- §3.9 — insert — ambiguity — `occurred_on` stamped as a calendar date (`YYYY-MM-DD`) — implementation/routes/mentorship.py:145
- §3.9 — revise — ambiguity — `separation_reason` accepted but not persisted — implementation/routes/physicians.py:76-107

**Deliberately left unchanged** (PRD already pins impl behavior uniquely): segregation-of-duties ordering, unique-then-ordered check-in checks, half-open template overlap with touching allowed, closed-interval event overlap with adjacency conflicting, campaign budget ledger, draw/forgiveness/outstanding formulas and pinned evaluation order, rounding pipeline, epoch-sweep ordering and strict-vs-inclusive date comparisons, OCC field name/`ERR_STALE_VERSION`, and the full error catalogue. Framework fallbacks (Flask 404/405/500 handlers in app.py returning the error envelope) were treated as outside the API contract and not pinned.
