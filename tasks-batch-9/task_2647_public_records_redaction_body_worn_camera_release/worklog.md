# Worklog — task_2647_public_records_redaction_body_worn_camera_release

## Step 1: Create task directory — 2026-09-04T00:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2647_public_records_redaction_body_worn_camera_release` and its `workspace/` subdirectory. Index 2647 was pre-assigned by the invoker; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T02:34:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2647_public_records_redaction_body_worn_camera_release/`

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2844 | §1.0–§1.7 only (top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1974 | single key `scaffold_difficulty_design`, 18 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2904 | single key `scaffold_corner_design`, 90 instances |

## Domain shape

13 entities, 48 endpoints (27 write / 21 read), 5 parallel state machines, 13 calculations, 33 prioritized validations, 2 concurrency rules. `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

## §1.9 coverage

All nine sections in canonical order: entities 12, state_machines 16, calculations 17, validations 20, endpoints 5, errors 9, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1 — 70 full `test_recipe` instances plus 20 `excluded_because` stubs. Every one of the 18 §1.8 instances is cited by at least one stub (zero uncited), no duplicate instance names, no instance carrying both a recipe and a stub.

Final section written this pass: two OCC recipes (one per §1.2.1 rule — a stale `expected_request_version` on `fee-estimates` and a replayed `scope-clarification` that proves the refusal spends neither a version nor one of the two clarification slots), a `retention_locked` reconciliation walk across both branches of its disjunction (including the point where the purge refusal changes code from `ERR_RETENTION_HOLD_ACTIVE` to `ERR_ASSET_STATE_INVALID` because a hold-locked asset is `SUSPENDED` and fails priority 8 first), a variant-switch instance where a withdrawal stales the quote and drops the request's mirrored `estimated_total_cents` to 0 while the STALE row keeps its 3150, two cascade stubs, and one `immediate` consistency instance.

## Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    48
  §1.8 instances scanned:     18
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  1054
```

Two violations surfaced on the first run, both in the consistency instance and both fixed: `submit-qa` was missing the required `logged_labor_minutes`, and `qa-outcome` carried an undeclared `qa_note`. Three further bugs were caught by hand before linting, since the linter cannot see them: `release-packages` takes only `media_type` (`package_kind` is computed, so a supplied `package_scope` was removed), the ledger list form is `GET /records/fee-ledger-entries?request_id=...` rather than a request sub-resource, and the invoice needed a preceding fee estimate because the `-> INVOICED` precondition set excludes `NOT_ASSESSED` and would otherwise have returned `ERR_FEE_STATE_INVALID`.

No sibling task directory was read at any point; the scaffold derives only from the scenario text and the skill specification.

## Step 3: Copy shared files — 2026-09-04T02:36:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T02:54:00.000Z

PRD.md is complete.

**Output:** `workspace/PRD.md` — **453 lines / 101376 bytes.** Orchestrator verified the tail independently: the file ends on the final row of the §5 Error Code Catalogue table (`| ERR_ENTRY_ALREADY_REVERSED | 409 |`), a real section boundary, not mid-sentence. No truncation; no regeneration needed.

Top-level headings are exactly `## 1. Introduction`, `## 2. Global Specifications & System-Wide Principles`, `## 3. Business Logic & Workflows`, `## 4. Endpoint Definitions`, `## 5. Error Code Catalogue` — no audit footer, no contract-report section. §2 has 11 subsections (2.1–2.11), §3 has 9 (3.1–3.9, within the 5–9 bound). §2.2 is byte-identical to `section-2.2-response-structure.md`.

**Contract 1 — Field-Name Coverage: PASS**
- Pass A (structured): 133 required identifiers (all `entities[].fields[].name` plus every `input` / `query_params` identifier across all 48 endpoints); backticked tokens extracted from PRD.md after stripping fenced code blocks; **diff empty, 0 missing**.
- Pass B (independent raw-YAML regex over `- name:` and list-item scalars): 147 candidates, 23 residual — all of them calculation names (`fee_estimate_total`, `fee_invoice_total`, `record_release_posture`, `release_eligible_set`, `clip_overlap`, `qa_window_conflict`, `statutory_deadline`, …), complexity-layer labels (`optimistic_concurrency`, `dual_variant_calculation`, …) and dual-variant basis labels. None is an entity field or endpoint I/O identifier; all are rendered as prose per the no-pseudocode rule.
- Also confirmed present: `id`, `created_at`, `updated_at`, `version`, `expected_request_version`; every state name from all 9 state machines; every calculation constant; both `concurrency_rules` error IDs.

**Contract 2 — Rule Coverage: PASS**
- Scaffold rules: 33 validations + 2 concurrency rules + 15 calculations + 9 state machines.
- §2.11 ladder items: 33 numbered entries, one per validation, in priority order 1→33.
- Error IDs named in §2.11: **33/33** (items 4, 5 and 17 tightened during verification so they name their codes inline rather than only cross-referencing §2.5/§2.10).
- `applies_to` enumerated for every ladder entry.
- Both pinned cross-band conflicts stated explicitly: priority 9 `ERR_REQUEST_NOT_RELEASE_READY` beats priority 30 `ERR_DEPOSIT_UNPAID`; priority 12 `ERR_RECORD_RELEASE_BLOCKED` beats priority 21 `ERR_CLIP_OVERLAP`. (These are the only two out-of-sequence first mentions — intentional forward references; both still have their own in-order numbered entries at 21 and 30.)
- All 52 error IDs appear in prose before §5, and §5 reproduces all 52 with statuses matching the scaffold exactly (0 mismatches, 0 extra, 0 missing).
- §4: 48 rows, exactly 4 columns, method+path set identical to the scaffold's, role lists identical on every row. §5: 52 rows, exactly 2 columns.

**Contract 3 — §3 Path Purity: PASS**
- 1072 backticked spans between `## 3.` and `## 4.`: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos, 0 raw (unbackticked) `/records/...` paths, 0 bare HTTP verb words anywhere in §3.

No fuzzy quantifiers (`approximately` / `roughly` / `conservatively`) anywhere in the document. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; no `pkill` was run.

## Step 5: Generate unit tests — 2026-09-04T03:58:00.000Z

Test generation is complete for `task_2647_public_records_redaction_body_worn_camera_release`.

## What was produced

Both output dirs live at the **task root** (verified: no `test_helpers/` or `test_suite/` anywhere under `workspace/`; `workspace/` still holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`, which I never read or touched).

- `test_helpers/` — 1,728 lines across 9 modules (`api_client` 267, `fixtures` 374, `factories` 327, `constants` 203, `types` 208, `api_errors` 145, `assertions` 132, `test_users` 71, `__init__` 1).
- `test_suite/` — 11,218 lines, **217 tests** in 18 files plus `conftest.py`:
  - Queue A (difficulty, written directly): `test_01`…`test_09`, 47 tests, 290/296/317/324/229/306/242/318/364 lines.
  - Queue B (corner, written by 7 section-partitioned subagents): `test_10_corner_entities` 1081, `test_11_corner_state_machines` 1317, `test_12_corner_calculations` 952, `test_13_corner_validations_a` 1099, `test_14_corner_validations_b` 804, `test_15_corner_endpoints` 844, `test_16_corner_errors` 1102, `test_17_corner_rbac` 429, `test_18_corner_cross_cutting` 883.

## Audit results (all machine-checked, zero failures)

- **Coverage**: all 18 difficulty instances (each ≥2 tests) and all **70 non-stub** corner instances of the 90 total (each ≥1 test). None of the 20 `excluded_because` stubs was translated.
- **Tagging**: every one of the 217 docstrings ends with exactly one `Design: Difficulty/…` or `Design: Corner/<section>/<name>` line naming a real, correctly-sectioned instance. No untagged or dual-tagged tests.
- **Citations**: all 217 `PRD: "…"` sentences verified as byte-for-byte substrings of `workspace/PRD.md`.
- **Static health**: every module imports cleanly against `test_helpers/`; every `api.<method>` exists on `ApiClient`; arity check of all fixture/factory/assertion/client calls passes; zero unused imports; no duplicate defs; no prints, sleeps, servers, or pytest runs. `__pycache__` from the import smoke was removed.

## Design defects found (assertions deliberately omitted, gaps left as gaps)

Seven instances contained values the PRD does not derive; in each case the rest of the instance was kept and the single assertion dropped:
- Two difficulty instances assert `processing_status == EXEMPTION_REVIEW` where PRD ¶251/¶257/¶271 derive `RELEASE_READY` / `REDACTION` (`redaction_task_qa_rework_cycle_repeats_qa_pending`, `blocked_posture_safety_beats_clip_overlap_constraint`).
- `extension_at_the_ceiling…` expects `ERR_VALIDATION` for 11 extension days, but §3.3 clamps to ten at clarification.
- `record_with_only_cancelled_tasks_is_not_releasable` and `interim_package_covers_only_the_record_with_an_approved_task` assume a `REDACTION → RELEASE_READY` edge the PRD grants only on a passing verdict or the full-withhold cascade.
- `fiscal_calls_on_an_unassessed_request…` expects `ERR_FEE_STATE_INVALID` on a payment where §3.10 derives `ERR_PAYMENT_EXCEEDS_OUTSTANDING`.
- Several instances used undeclared enum values (`retention_category: PERMANENT`, `hold_type: CIVIL_RIGHTS_SUIT`) or undocumented list filters (`?status=` on redaction tasks, `?disposition_state=` on assets); these were repaired to declared values or replaced with direct re-reads.

One item for the implementation side: PRD ¶323 lists `retention_locked` as an `ERR_RETENTION_HOLD_ACTIVE` trigger on release, yet ¶321's seven-condition releasability list omits it — taken literally the two conflict, since every recording on an open request is retention-locked. The suite follows ¶321 (releases succeed), consistent with every design instance.

## Step 6: Generate implementation — 2026-09-04T03:35:00.000Z

The implementation for task 2647 is complete, verified, and the boot-verification server has been shut down (PIDs 810240/810242 on port 41777 killed individually; port confirmed free — no broad `pkill` was ever used).

## Deliverable

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
`requirements.txt` | 1 | Flask pin
`start.sh` | 11 | `$PORT` (default 10000), `exec python3 app.py`, foreground, conditional pip
`app.py` | 77 | `create_app()`, 8 blueprints, envelope error handlers, `0.0.0.0` bind
`db.py` | 123 | in-memory `Store` (13 dicts), logical clock, ISO-8601 helpers, snapshot/restore
`errors.py` | 78 | all 53 error codes → HTTP status
`response.py` | 63 | meta/`api_request_id`/pagination envelope
`middleware.py` | 72 | 6 roles, `X-User-ID`/`X-User-Role`, entity-backed principal resolution
`validate.py` | 185 | typed field extractors + pagination bounds
`calc.py` | 577 | all enums, constants and every PRD formula
`serialize.py` | 16 | projection/field ordering
`core.py` | 110 | `write_endpoint`/`read_endpoint` (lock → snapshot → auth → handler → reconcile → version bump; rollback on error)
`reconcile.py` | 132 | re-query reconciliation of every derived field
`services.py` | 132 | deadline restrike, ledger writes, state-machine junctions, cascades
`routes/directory.py` | 71 | 4 endpoints
`routes/assets.py` | 187 | 10
`routes/requests.py` | 222 | 7
`routes/review.py` | 228 | 7
`routes/redaction.py` | 199 | 5
`routes/fees.py` | 201 | 7
`routes/endgame.py` | 246 | 7
`routes/clock.py` | 20 | 1
`routes/__init__.py` | 0 | package marker

**2951 lines total; `@bp.route` count = 48, matching the SCAFFOLD endpoint count exactly.** All 22 files pass `python3 -m py_compile`; `__pycache__` removed.

## Constraint compliance
- Storage is in-memory dicts only — no SQLite, no disk JSON, no `/tmp` cache, and zero seeded/preloaded entities. Startup clock is pinned to `2026-08-01T00:00:00Z`, so a fresh process per test is fully deterministic.
- Every file was written in chunked `cat >> … <<'EOF'` appends; no one-shot Write, so nothing was truncated by the 64k cap.
- Boot verified on a self-chosen port (41777), then killed by recorded PID.
- `test_suite/`, `test_helpers/` and all sibling task dirs were never read. `PRD.md` and `worklog.md` untouched.

## Verification (3 end-to-end smoke scripts, all `FAILURES: 0`)
Confirmed numerically: 20 review minutes for a 10-min USE_OF_FORCE asset; baseline obscuration 3; PERSONAL_PRIVACY partial claim 4 min; invoice 2100 labor + 500 media = 2600 with `LABOR_CHARGE −2100`/`MEDIA_CHARGE −500` and the zero `WAIVER_CREDIT` correctly skipped; ledger conservation identity holds; critical-incident deadline floor; 45→30-minute QA buffer boundary (11:30 conflicts, 11:31 clears); QA load cap at 3 open assignments; adjacent clip intervals accepted while 1 ms penetration is `ERR_CLIP_OVERLAP`; JUVENILE 15-day objection window; objection-materialised claim with null asserter; FULL_WITHHOLD → `WITHHELD_IN_FULL`/`BLOCKED` cascade; FULL denial → `DENIED`, appeal `REVERSED` → back to `EXEMPTION_REVIEW` with claims `WITHDRAWN`; OCC 412 on a stale `expected_request_version`; litigation-hold suspend/release and purge due-date/lock refusals; `rework_count` incrementing only from `QA_REJECTED`.

## Spec ambiguities resolved (§2.11 ladder treated as authoritative over narrative order)
Fee-state check precedes readiness on invoice; requester-mismatch precedes letter-state on appeal; certification (step 11) precedes release posture (step 12) on task creation; `ERR_INVALID_AMOUNT` (not `ERR_VALIDATION`) for non-positive payments; `ERR_INVALID_CLIP_RANGE` for any clip-bound violation; release does **not** trigger `CLOSED` (only invoice/payments do, per the SCAFFOLD triggers); a FINAL package requires no `CANDIDATE` record; `DenialLetter` carries a hidden `_issued_by_staff_id` for appeal-decision segregation; the clock endpoint echoes the raw supplied string. `destruction_note` and `expected_request_version` were verified as input-only fields that are correctly not persisted.

No implementation defects were found by any smoke run.

## Step 7: Run tests and iterate — 2026-09-04T04:35:00.000Z

Sweep 3 is fully green: **217 passed / 0 failed / 217 total in all 8 concurrent rounds.**

## Summary

**Iterations run: 3 full 8-round parallel sweeps**
- Sweep 1: 175/217 in every round (42 deterministic failures, identical failing set in all 8 rounds — no flakiness, so no host-load filtering was needed)
- Sweep 2: 216/217 in every round (1 failure)
- Sweep 3: 217/217 in all 8 rounds

**Tests deleted: none.** No whole test was PRD-silent at the test level. Four individual assertions were removed under STEP 1c (partial coverage — keep the covered assertion, drop the uncovered one):
- `test_suite/test_16_corner_errors.py` — dropped `disposition=None` on the exemption-claim resource. PRD §3.5 says `disposition` is an adjudication *input* that "is also the `status` the claim will carry afterwards"; the claim resource carries `status`, not a separate `disposition` field. COMPUTED-FIELD SILENCE. Replaced with `adjudicated_by_staff_id=None`.
- `test_suite/test_03_non_linear_state_machine.py` — dropped `estimated_total_cents=5000` after a sustain staled the only estimate.
- `test_suite/test_04_transitive_cascade.py` — dropped `estimated_total_cents=1750` in the same situation. PRD §3.8 says verbatim the mirror figures "are 0 whenever no `ACTIVE` estimate exists", and `test_18_corner_cross_cutting.py::test_the_two_bases_reconverge_once_the_claim_is_gone` asserts `== 0` in exactly that state ("A stale quote mirrors nothing") — the suite contradicted itself, proving the retained-mirror reading is not uniquely derivable.
- `test_suite/test_07_cross_entity_state_dependency.py` — dropped the hardcoded `expected_request_version=1` in the clarification. The earlier `attach_record` recomputes `responsive_record_count`, which under PRD §2.7 ("one rule with no exceptions") bumps the request to version 2; the helper now reads the version the caller last observed.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `parse_instant`, `same_instant`, `assert_instant`, and made `assert_fields` fall back to instant-equality when both sides are ISO 8601 strings. PRD §2.2/§2.5 pin three fractional digits only on `created_at`, `updated_at` and `meta.api_request_timestamp`; for the ~15 other instant fields (`deposit_due_at`, `statutory_deadline_at`, `objection_deadline_at`, `appeal_deadline_at`, `notified_at`, `released_at`, `issued_at`, `placed_at`, `adjudicated_at`, `appeal_filed_at`, `appeal_decided_at`, `qa_window_start_at`, plus echoed inputs) the rendering is not derivable while the instant is — so `…T00:00:00Z` and `…T00:00:00.000Z` now agree, while a deadline one second or one day out still fails. This one change fixed ~37 tests without weakening any boundary check.
- `test_suite/test_12_corner_calculations.py` — the only file with raw (non-`assert_fields`) instant string comparisons; routed its two through `assert_instant` / `not same_instant`.

**Fixes applied to `implementation/`: none (net).** The one change attempted — making `reconcile.py::_reconcile_requests` mirror the newest `ACTIVE`-or-`STALE` estimate — was reverted after sweep 2 showed it broke `test_18`; the verbatim PRD §3.8 sentence governs, so the ACTIVE-only filter stands. Only a PRD-citing comment remains at `workspace/implementation/reconcile.py:52-53`. No endpoint, field, side effect or seeded data was added anywhere; storage remains in-memory dicts only.

### Orchestrator verification

Independently re-read all eight `workspace/implementation/results.{1..8}.json`: every round reports `passed=217 / total=217 / failed=0`. Sweep artifacts are present and complete, so the green claim is confirmed rather than taken on trust.

### Step 8 decision

Step 7 made 0 net `implementation/` fixes, but it did make `test_suite/` and `test_helpers/` fixes and dropped four assertions under STEP 1c. The skill's skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; that is not met here, so Step 8 runs.

## Step 8: Finalize PRD — 2026-09-04T04:45:00.000Z

Done. Two edits, both traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 453 lines — `PRD_FINALIZED.md`: 455 lines (+2 lines, **+0.44%**). Two hunks total: one inserted paragraph, one in-place sentence append.

## Changes
- **§2.5 Common Resource Properties — insert** — added one paragraph pinning the rendering of *every* non-null instant field beyond `created_at`/`updated_at`: ISO 8601 UTC ending in `Z` with exactly three fractional digits, applying both to derived/stamped instants and to instants echoed back from request input (which are normalised to UTC and re-rendered, not returned as spelled: `2026-08-11T14:22:00Z` → `2026-08-11T14:22:00.000Z`) — `implementation/db.py:51-60` (`fmt_dt`), `implementation/db.py:82-83` (`now_str`).
- **§3.5 Adjudication — revise** — appended: "`disposition` is an input field only: the claim resource records the outcome in its `status` and carries no `disposition` field of its own." — `implementation/routes/review.py:91,103` (input consumed, written to `status`), `implementation/routes/review.py:68-82` (created claim field set).

## Per-edit pre-edit search log

**Edit 1 (§2.5 instant rendering)**
- (a) Subject: the wire rendering of every instant-valued field on every resource and in `meta`, including echoed request inputs.
- (b) Enumerated/read: `db.py:33-60` (`parse_dt` → always converts to UTC; `fmt_dt` → always `%03d` fractional digits), `db.py:82-83` + `response.py:19-23` (`meta.api_request_timestamp`), `core.py:30-44` (`updated_at` stamp), `db.py:105-113` (`created_at`); then grepped every `*_at` / `*date*` field write across `routes/*.py`, `services.py`, `calc.py`: `requests.py:58,60-61,68,70,114-115,156`, `assets.py:42,47,74-75,115-116,130`, `review.py:78,105,154-155,196`, `redaction.py:72-73,130-131`, `fees.py:75`, `endgame.py:92,95,106,148-149,152-153,179,198`, `services.py:10,132`. Every non-null instant is produced by `fmt_dt(...)` or `store.now_str()`; the single non-literal case (`endgame.py:106`) uses `stamp = fmt_dt(clock)` from `endgame.py:92`. No `recorded_end_at`/`purged_at`-style extra instant exists. Cross-checked §2.4's own `2026-08-01T14:22:00.000Z` example for consistency.
- (c) Adjustment: stated the rule universally ("every other instant-valued field on any resource") with the field names given only as illustrations rather than as a closed list, so a field not named cannot be read as excluded; added the "whenever it is not null" qualifier because many of these fields open as `null` (`requests.py:68,70`, `assets.py:74-75`, `redaction.py:72-73`, `endgame.py:152-153`).

**Edit 2 (§3.5 `disposition`)**
- (a) Subject: whether `disposition` is persisted on the exemption claim, i.e. the claim's persisted field set.
- (b) Enumerated/read: both claim-creation paths (`review.py:68-82` staff assertion, `review.py:190-205` objection-sourced claim) — neither stores `disposition`; the adjudication handler `review.py:89-112` (input validated at :91, written to `claim["status"]` at :103, plus `adjudicated_by_staff_id`/`adjudicated_at`/`adjudication_note`); the appeal-reversal sweep `endgame.py:207-210` which sets `status = "WITHDRAWN"` without any disposition/adjudication stamp; `serialize.py:9-12` (generic projection of stored keys, so no computed field is injected at read time); and a repo-wide grep for `disposition` confirming the only other occurrences are the video asset's unrelated `disposition_state` (`assets.py:48,86-95,150-159`, `reconcile.py:84-92`, `calc.py:564`, `requests.py:137`).
- (c) Adjustment: scoped the sentence to the claim resource only (not "no resource carries a disposition field"), which keeps `video_assets.disposition_state` correctly described; and phrased it as "records the outcome in its `status`" without claiming the adjudication stamp fields are always set, since `endgame.py:209`'s reversal moves a claim to `WITHDRAWN` without touching `adjudicated_at`/`adjudicated_by_staff_id`.

## Items deliberately not patched
- **Stale-estimate mirror (`estimated_total_cents` / `deposit_required_cents` → 0)**: §3.8 already says verbatim the request figures "are 0 whenever no `ACTIVE` estimate exists", and `reconcile.py:54-62` filters `ACTIVE` only. PRD already determines it; the dropped assertions were test-side contradictions.
- **`expected_request_version` after `attach_record`**: §3.4 states the attachment recomputes the request's `responsive_record_count`, and §2.7's "one rule with no exceptions" then bumps the request's `version`; `core.py:30-44` bumps exactly on changed projections. Already determined — the hardcoded `1` was a fixture bug.

## Step 9: Complete PRD — 2026-09-04T05:05:00.000Z

Run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than a single subagent, because a single-pass scan of a 22-file / 2951-line implementation against a 456-line PRD has historically no-opped (producing a byte-identical copy). Each pass owned a disjoint slice of `implementation/` but was allowed to read the whole tree for context, and pass 3 additionally swept the document for contradictions the three passes might have introduced between them.

### Pass 1/3 — app, core, middleware, response, serialize, validate, errors, db, routes/{directory,assets,requests,clock}

- `PRD_FINALIZED.md` 455 lines / 102,380 chars → `PRD_COMPLETED.md` 456 lines / 108,600 chars (+6,220 chars; the one added line is a bullet on the §2.2 error-format list — no new sections).
- **19 ambiguity-pins, 2 mismatch-revisions.**
- §2.1 — insert — `GET /records/requests` applies the filer rule as *scoping* (omitted `requester_id` silently narrows to own rows); only an explicitly foreign `requester_id` raises `ERR_REQUESTER_MISMATCH` — routes/requests.py:180-183
- §2.2 — insert — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — response.py:7,16
- §2.2 — insert — `api_request_timestamp` is read from the logical clock, not wall time — response.py:22
- §2.2 — insert — undeclared path → `ERR_VALIDATION`/404, unsupported method → `ERR_VALIDATION`/405, unparseable JSON → `ERR_VALIDATION`/400; trailing slash equivalent to its absence — app.py:37,49-62
- §2.3 — insert — empty-string `limit`/`offset` take defaults, non-integer values are `ERR_VALIDATION`, `offset` has no upper bound, past-end pages return empty `data` with `has_more` false — validate.py:150-169, response.py:36-42
- §2.3 — insert — `created_at` ties broken by insertion order — db.py:101-103
- §2.3 — insert — filters optional/independent, ANDed, empty-string = no restriction, enum filters reject undeclared values with `ERR_VALIDATION`, identifier filters match by exact equality and never 404 — validate.py:172-185
- §2.4 — insert — a clock write bumps no `version` and reconciles nothing; answers 200 / `response_type` `object` / `data.current_utc` echoed verbatim, *not* re-rendered to three fractional digits — routes/clock.py:13-20
- §2.5 — insert — input parsing accepts `Z`/`z` or a numeric offset, treats a zoneless instant as UTC, truncates sub-millisecond digits rather than rounding; unparseable → `ERR_VALIDATION` — db.py:33-60, validate.py:110-127
- §2.7 — insert — a rejected write is fully rolled back: no row left behind, no half-reconciled counter, no `version` movement — core.py:69-84
- §2.7 — insert — no-op writes bump nothing; the diff excludes `updated_at`/`version`; a child-only write does not bump an unchanged parent; created rows stay at `version` 1 with `updated_at` = `created_at`; the two §2.6 writes always bump — core.py:15,30-44
- §2.11 step 3 — insert — absent/empty body = empty JSON object; a non-object body is a schema failure; explicit `null` counts as absent (required rejects, optional defaults); bool≠int, number≠string, string-array elements enforced — validate.py:16-24,27-31,69,134
- §3.1 — insert — `email` is a required string with no address-format check — routes/directory.py:40
- §3.2 — insert — `notified_at`, `objection_deadline_at`, `objection_basis` all null at creation — routes/assets.py:74-76
- §3.2 — insert — `release_note` validated as a string but not persisted — routes/assets.py:125
- §3.2 — insert — `destruction_note` validated as a string but not persisted — routes/assets.py:84
- §3.3 — insert — `deposit_due_at` null and `scope_clarification_count` plus all eleven derived counter/money fields start at 0 — routes/requests.py:63-81
- §3.3 — **revise / mismatch** — PRD said `extension_days_granted` is "stored as the lesser of the supplied value and ten"; impl rejects >10 as `ERR_VALIDATION` and never clamps — routes/requests.py:95-97
- §3.4 — **revise / mismatch** — request state is tested before recording state, so a destroyed recording on a `CLOSED` request reports `ERR_REQUEST_STATE_INVALID`; every non-`CLOSED` status (incl. `DENIED`/`RELEASED`) accepts the attachment — routes/requests.py:134-139
- §4 (4 rows) — revise — pinned list-filter parameter names for requests / video-assets / depicted-individuals / responsive-records — routes/assets.py:148-151,167, routes/requests.py:176-179,209-212
- Verified out-of-partition: `ctx.touch` occurs only at routes/requests.py:123 and routes/fees.py:79 (exactly the two §2.6 writes), so the no-op version rule and its carve-out hold globally. §5 already matched `errors.py` exactly.

### Pass 2/3 — routes/{review,redaction,fees}

- 456 lines / 108,600 chars → 456 lines / 114,808 chars (+6,208; all in-paragraph).
- **12 ambiguity-pins, 9 mismatch-revisions.**
- §2.10 — revise — mismatch — "four write operations … all four report `ERR_CLAIM_RECORD_MISMATCH`" reduced to exactly two (task creation, objection); the claimed reversal check does not exist (reversal takes its target from the path, accepts no `reverses_entry_id`) and claim assertion cannot fail — routes/fees.py:142-156, routes/review.py:49-84
- §2.11 step 16 — revise — mismatch — "on the four writes named in §2.10" → the two writes (redaction-task creation, objection recording) — routes/redaction.py:50, routes/review.py:175
- §3.3 — revise — mismatch — deadline recomputation happens only on rulings that find a record `RESPONSIVE`; an `EXCLUDED` ruling leaves `statutory_deadline_at` frozen — routes/review.py:41-45
- §3.3 — revise — mismatch — `deposit_due_at` is set by *every* estimate landing in `DEPOSIT_DUE` (re-stamped on a superseding estimate), not only the first, and is never cleared — routes/fees.py:73-77
- §3.4 — insert — the record's `inclusion_status` is tested *before* the parent request's `processing_status` (opposite of the attachment write), so `ERR_RECORD_STATE_INVALID` wins — routes/review.py:33-39
- §3.4 — insert — `EXCLUDED`/`RELEASED` are the only inadmissible states for an exemption assertion; `CANDIDATE`/`WITHHELD_IN_FULL` accept, and `processing_status` is untested — routes/review.py:59-62
- §3.5 — insert — the two-outcome fork applies only from `EXEMPTION_REVIEW`; from `REDACTION` a simpler test runs after every disposition (all tasks terminal + one `RESPONSIVE` record → `RELEASE_READY`), including with no task; other statuses never move — services.py:80-102
- §3.6 — insert — the four guards plus certification are the whole guard: neither the record's `inclusion_status` nor the request's `processing_status` is examined — routes/redaction.py:34-63
- §3.6 — insert — `assigned_technician_id` need only resolve to a staff row; `role_type` is never checked — routes/redaction.py:36
- §3.6 — insert — `logged_labor_minutes` is a required non-negative integer; a negative value is `ERR_VALIDATION`, not a fiscal code — routes/redaction.py:91
- §3.6 — insert — the nominated reviewer's `role_type` is never examined — routes/redaction.py:96-112
- §3.6 — insert — an omitted `defect_codes` stores the empty array on a `FAIL` — routes/redaction.py:140,164
- §3.6 — revise — mismatch — "including `EXCLUDED` ones, whose tasks are cancelled and therefore contribute nothing anyway" is false; nothing cancels a task because its record was excluded, so approved work on `EXCLUDED`/`CANDIDATE` records does count — reconcile.py:29-34,47-48
- §3.7 — insert — the recording match is the only test on the named record; its `inclusion_status` and the request's `processing_status` are untested — routes/review.py:169-181
- §3.8 — insert — an estimate stores only `media_production_cents`; `produced_minutes`/`disc_count` are stored fields only on the release package — routes/fees.py:51-67, calc.py:320-336
- §3.8 — revise — mismatch — the `WAIVED` path writes no ledger line when `waiver_credit_cents` is 0 (free-allowance case), so the "full waiver credit is written" claim is now conditional — routes/fees.py:68-72, services.py:26-28
- §3.8 — insert — the zero test precedes the threshold test, so `WAIVED` is reachable from `NOT_ASSESSED`, `ESTIMATED` and `DEPOSIT_DUE` alike; the closure junction fires inside the estimate call — routes/fees.py:68-78
- §3.8 — insert — no operation ever emits a `REFUND` line; the value is reserved (and that is what keeps §2.8's conservation identity exact) — services.py:24-36, calc.py:436-455
- §3.8 — revise — mismatch — dropped "evaluated against the request's current `fee_status`" (the ceiling never consults it); a request owing nothing has a ceiling of 0 and refuses with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `WAIVED` being the only state-rejected case — routes/fees.py:93-103
- §3.8 — insert — fee-state test precedes readiness on invoicing (`ERR_FEE_STATE_INVALID` wins); a second invoice is that same failure; the call answers 200 with the **request** resource, there being no invoice entity — routes/fees.py:110-139
- §3.8 — revise — mismatch — the two demotion conditions are independent (`OR`), not "equivalent" — reversing a waiver credit trips only the balance test — and `SETTLED` is the only state demoted — routes/fees.py:157-162
- §3.9 — revise — mismatch — closure also fires inside a fee estimate that prices the request out to `WAIVED`, not only in invoicing/payment — routes/fees.py:78, services.py:40-43
- §4 — revise ×3 — exemption-claim, redaction-task and fee-estimate list filters spelled out; fee-estimate ordering pinned to ascending `sequence_number` — routes/review.py:216-228, routes/redaction.py:188-199, routes/fees.py:193-201
- Non-changes: every ladder position exercised by these three routes already matched §2.11 exactly (estimate `7→8→19`, payment `6→8→31→32`, task creation `11→12→16→20→21→30`, submit-qa `8→10→11→25→26→27`, objection `8→16→28`); the half-open clip-overlap formula, the buffered closed-endpoint QA window, the eleven estimate steps, the five invoice steps and the three-line invoice ledger order were literal matches.

### Pass 3/3 — routes/endgame, services, reconcile, calc + whole-document consistency sweep

- 456 lines / 114,808 chars → **456 lines / 118,931 chars** (+4,123; all in-paragraph, no lines added or removed).
- **4 ambiguity-pins, 5 mismatch-revisions.**
- §2.7 — insert — named the fields reconciliation deliberately never re-derives (`estimated_review_minutes`, `estimated_redaction_minutes`, `statutory_deadline_at`, `tolled_days`, `deposit_due_at`, `invoiced_total_cents`, every FeeEstimate/DenialLetter/ReleasePackage money field, both status dimensions); PRD had never pinned `invoiced_total_cents` as frozen after invoicing — reconcile.py:1-9,52-62
- §3.2 — revise — mismatch — a newly placed hold does not take ownership of every matching recording; ownership goes to the matching `ACTIVE` hold with the smallest `created_at`, so a second hold over the same incident suspends nothing and settles at `suspended_asset_count` 0. `retention_locked` is still recomputed for `PURGED` recordings — reconcile.py:86-89,96-103
- §3.9 — revise — mismatch — "the notification sweep runs first, before anything else in the call" is false; impl runs it after all six guards. Replaced with the observationally accurate statement (atomic rollback + the eligibility test already treats `NOTIFIED`-past-deadline as satisfied) — routes/endgame.py:91, core.py:78-84
- §3.9 — revise — mismatch — the four release guards scan **every** `RESPONSIVE` record of the request (not only records the package would release) and consult only matching `ACTIVE` holds; reading `retention_locked` would refuse every release ever. `PENDING`/`OBJECTION_SUSTAINED` raise no code and only drop the record from the eligible set — routes/endgame.py:57-78
- §3.9 — insert — the final-package `CANDIDATE` bar is `ERR_REQUEST_STATE_INVALID`, does not compete with `ERR_NO_RELEASABLE_RECORDS`, and sits above the deposit check; the `PARTIALLY_RELEASED → PARTIALLY_RELEASED` interim self-loop is pinned — routes/endgame.py:83-88,109
- §3.9 — revise — mismatch — FULL-denial "every retained record must be `WITHHELD_IN_FULL`" had no code and is evaluated *below* the unadjudicated-claim check, contradicting rung 8 of §2.11; pinned `ERR_REQUEST_STATE_INVALID` plus the explicit ladder exception — routes/endgame.py:124-134
- §3.9 — revise — mismatch — a `FULL` denial reaches `DENIED` from `REDACTION` and `RELEASE_READY` as well as `EXEMPTION_REVIEW`; `statutory_citations`/`withheld_record_count` are frozen issuance snapshots; the issuing attorney is internal-only (no field on the letter) — routes/endgame.py:135-158
- §3.9 — insert — an appeal reversal drives only the `DENIED → EXEMPTION_REVIEW` edge; a request standing elsewhere keeps its `processing_status` and the §3.5 auto-advance tests are not re-run — routes/endgame.py:204-217
- §4 — revise — the `GET /records/requests/{id}/denial-letters` row now names its `status` filter and the four-value domain — routes/endgame.py:233
- Verified with no change needed: every enum, constant, formula and rounding rule in `calc.py` (all 30 enumerations, both waiver/tier ladders, `certification_requirement`, `statutory_deadline`'s three steps and floor guard, `tolled_days_for_payment`, clip half-open vs QA closed+30-minute buffer semantics, `ledger_figures` reversal attribution); every junction and cascade in `services.py`; the rest of `reconcile.py`'s query definitions.
- Consistency sweep clean: `retention_locked` now gates only destruction (§3.2/§3.9), `ACTIVE`-hold matching gates only release, and the "smallest `created_at`" hold-ownership rule reads identically at all three sites.

### Orchestrator verification

- `PRD.md` 453 lines / 101,376 chars → `PRD_FINALIZED.md` 455 / 102,380 → `PRD_COMPLETED.md` 456 / 118,931.
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (105 differing lines), so the scan demonstrably ran rather than no-opping.
- All five top-level headings intact; the document still ends on the final row of the §5 Error Code Catalogue table (`| ERR_ENTRY_ALREADY_REVERSED | 409 |`) — no truncation.
- Nothing under `test_suite/`, `test_helpers/` or `workspace/implementation/` was modified after the green sweep at 04:35, so the 8×217/217 result remains the state of the delivered artifacts. `__pycache__` directories removed.

Pipeline complete through Step 9.
