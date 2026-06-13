# Worklog — task_0173_ediscovery_litigation_hold

## Step 1: Create task directory — 2026-06-05T13:40:32.000Z

Created `tasks/task_0173_ediscovery_litigation_hold/` and `tasks/task_0173_ediscovery_litigation_hold/workspace/` via `mkdir -p`. Pre-assigned index 0173 used exactly (no auto-increment). Scenario: eDiscovery & Litigation Hold.

## Step 2: Generate scaffold (Expert) — 2026-06-05T14:08:38.000Z

All three files are generated, parse cleanly, and the lint reports `VERDICT: clean lint`. The scaffold for task_0173_ediscovery_litigation_hold is complete.

## Summary

Generated three scaffold artifacts for **eDiscovery & Litigation Hold** at **Expert** difficulty in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0173_ediscovery_litigation_hold/`.

**Complexity profile**: workflow_orchestration + compliance_audit; flat topology (FK references, `api_prefix: /`); parallel state-machine shape; segregation_of_duties role model; immediate consistency. Layers: cascading side effects, dual-variant calculation, derived-field reconciliation, optimistic concurrency.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **12 entities**: Matter, Custodian, LegalHold, HoldAcknowledgement, CollectionScope, Document, ProcessingJob, ReviewBatch, DocumentReview, ProductionSet, ProductionItem (common_fields:false), Clawback — 20 FKs, all reverse-reachable.
- **8 state machines**: Matter (parallel: lifecycle_status × hold_status), LegalHold, HoldAcknowledgement, CollectionScope, ProcessingJob, ReviewBatch (cyclic QC bounce-back), ProductionSet (branching validate→BLOCKED|STAGED), Clawback. Includes reverts, auto-transitions, and a depth-4 release-hold cascade (Matter→LegalHold→CollectionScope→Document/Custodian).
- **1 concurrency rule**: OCC on ProductionSet.version guarding `POST /clawbacks` (412 ERR_STALE_VERSION).
- **5 calculations**: dedup_partition (chronological, matter-wide variant), collection_volume (estimate vs actual dual-variant), spoliation_risk_score (3-input non-linear tiered, provisional vs final), production_cost_cents (pinned round-per-doc-then-sum), bates_allocation (waterfall contiguous integer ranges).
- **15 validations** (ordered, with SoD, cross-entity, temporal-overlap, OCC).
- **60 endpoints** (CRUD + filtered-list reverse-reachability GETs + action endpoints + one `/_clock/set_current_utc` test-driving endpoint). Note: endpoint count runs above the Expert 20–32 band, driven by mandatory per-entity read/list endpoints for FK reachability; the interaction density (not volume) carries the difficulty.
- **19 errors**; **5 roles** (LegalOps/ReviewLead/Reviewer/Producer opaque, Custodian entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **18 instances** — all 9 Difficulty Rules × 2, each with fully-replayed `setup_api_calls` chains and code-computed literal asserts (e.g., produced_page_count==21, provisional/final risk 35/20 and 90/60, dedup 3+2==5, Bates [1,2]+[3,4]).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **37 instances** (29 active + 8 `excluded_because` stubs) across entities, state_machines, calculations, validations, endpoints, rbac, errors, cross-cutting layers, and consistency_model sections.

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint`; all 55 instance names unique across both design files; all `grounds` references resolve; all `excluded_because.difficulty_instance` refs valid; no forbidden concurrency vocabulary; enum-value closure satisfied (decision→tag freeze mapping made explicit); OCC write-endpoint bumps parent version per §1.2.1.

One design decision worth flagging: corrected the second `priority_pair_validation_conflict` instance during generation — the original "state-beats-safety after release" scenario was unreachable (a DEFINED scope isn't cascaded to RELEASED), so it was replaced with a genuinely dual-failing existence(404)-vs-temporal(422) conflict on `POST /collection-scopes`.

## Step 3: Copy INSTRUCTION.md — 2026-06-05T14:09:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0173_ediscovery_litigation_hold/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T14:15:01.000Z

Generated `workspace/PRD.md` (~284 lines, 38KB) from SCAFFOLD.yaml only. Both design files withheld.

**PRD section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Common Resource Properties + Computed-Field Reconciliation, 2.5 Hierarchical Consistency + Cascade Ordering, 2.6 OCC, 2.7 Bates Numbering + Production Cost Precision, 2.8 Validation Ordering + Nested Resource Resolution)
- 3. Business Logic & Workflows (9 subsections: matter/custodians, hold issuance/acknowledgement, spoliation risk scoring, collection, processing/dedup, review/tag-freeze, Bates production fork, clawbacks/concurrency, lifecycle close-out)
- 4. Endpoint Definitions (4-column table, 61 endpoints)
- 5. Error Code Catalogue (2-column table, 19 error IDs)

**Hard Contract reports:** Contract 1 (Field-Name Coverage) 59/59 present PASS; Contract 2 (Rule Coverage) 33-point spot-check PASS; Contract 3 (§3 Path Purity) 327 tokens, 0 path/method leakage PASS; §2.2 byte-identical; all 19 error IDs surfaced.

**Confirmation:** No SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml content was consulted.

## Step 5: Generate unit tests — 2026-06-05T18:08:44.000Z

(Note: original Step 5/6 run was interrupted by a session limit and left nothing on disk; both were regenerated concurrently in the resume run.)

Generated complete test infrastructure for the **eDiscovery & Litigation Hold** PRD benchmark task.

**Test files: 5** (plus `conftest.py`), **65 tests total**, all collected cleanly under pytest.

**Queue split:**
- **Queue A (Difficulty): 36 tests** covering all **18** difficulty instances, each with ≥2 tests (boundary precision, dual-variant calcs, combinatorial formulas, non-linear state machines, transitive cascades, priority-pair conflicts, cross-entity dependencies, temporal overlap, compensating invariants).
- **Queue B (Corner): 29 tests** covering all **29** non-stub corner instances, each with ≥1 test (entity CRUD/validation, state-machine guards, calculations, validations, RBAC, errors, cross-cutting reconciliation).

**Skipped instances: 0 of the translatable set.** The **8 `excluded_because` stubs** were not translated (correct per spec). No instance failed the PRD-first filter — every targeted rule is verbatim-covered and uniquely derivable from PRD prose.

**test_helpers files (9):** `__init__.py`, `types.py`, `api_client.py` (60 endpoint methods), `api_errors.py` (19 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 roles; Custodian entity-backed with `make_custodian_headers`), `fixtures.py` (tiered composite setup — full matter→hold→ack→collect→dedup→review→produce→clawback lifecycle).

**Verification:** All files byte-compile; test_helpers imports cleanly (159 exported names); all 65 tests pytest-collect with no import/fixture errors. C1 verbatim citation pass: all 70 quoted PRD sentences are literal substrings of PRD.md (fixed 17 initial mismatches). C4 scaffold-citation pass: every test carries exactly one `Design:` line; no untagged/dual-tagged/orphan tags. No skip/xfail markers.

PRD-fidelity note: for `production_set_validate_fork_blocked_vs_staged`, the BLOCKED branch is unreachable through clean PRD-only paths (a PRIVILEGED doc cannot be added as an item per §3.7; post-produce sets are terminal), so both tests assert the STAGED fork and its Bates-allocation side-effect.

## Step 6: Generate implementation — 2026-06-05T18:08:44.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`.

**Files:** `start.sh` (executable foreground launcher), `requirements.txt` (`flask==3.0.3`), `app.py` (entry point + error handlers + all 60+ routes), `db.py` (in-memory store, one dict per entity keyed by UUID4, monotonic `_seq`), `clock.py` (pinnable clock for `/_clock/set_current_utc`, ISO-8601 UTC 3 fractional digits), `errors.py` (ApiError + full catalog with HTTP mappings), `response.py` (meta/response_type/data envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `helpers.py` (pagination limit/offset default 10/1..100, round_half_up via Decimal, validation), `serializers.py` (per-entity public projection; ProductionItem keeps only id/created_at), `services.py` (computed-field recompute, calculations, cascades).

**Stack:** Python 3 + Flask only. `decimal.Decimal` with `ROUND_HALF_UP` for money/rate math.

**start.sh:** `set -euo pipefail`, cd to script dir, guarded install (install only if flask import fails), then `exec python3 app.py`. Reads `$PORT` (default 10000), binds `0.0.0.0`, foreground, `threaded=True`.

**Storage:** In-memory only — module-level dicts in db.py. No SQLite, no JSON/pickle dumps, no file writes, no seed helpers, no entity construction at import/startup. Grep confirmed zero persistence/seeding anti-patterns.

**Verification:** Two end-to-end suites pass against a live server: full lifecycle + edge cases. Confirmed: parallel lifecycle×hold axes, matter-wide content-hash dedup, three-hop release cascade, Bates contiguity (ABC000001), per-document-then-sum cost rounding (74 vs wrong 73), SoD block, OCC ERR_STALE_VERSION (412), provisional vs final spoliation risk, validation ordering (auth → forbidden-role → SoD → not-found → state → business rules).

## Step 7: Test-and-fix loop — 2026-06-05T18:18:21.000Z

Clean exit. All 8 parallel rounds pass 65/65.

**Iterations run:** 2 (initial sweep, then re-run after the fix).

**Root cause:** All 30 failing tests (stable across all 8 rounds — no flakiness) shared one setup error: `HTTP 422 ERR_INVALID_REQUEST - content_hash must be a hex string`. Classic ≥5-tests-same-setup-error triage signal pointing at test_helpers.

**Diagnosis (STEP 1 + STEP 2):**
- PRD §3.4 (`workspace/PRD.md:151`) states verbatim: *"Each document is supplied with the `scope_id` of its collecting scope, a non-empty **hexadecimal** `content_hash` used for duplicate detection..."* So the implementation's hex validation (`app.py:553`, `^[0-9a-fA-F]+$`) is PRD-faithful and must NOT be weakened.
- The bug was in test_helpers: the suite passed short human-readable content-hash labels (`"A"`, `"DUP"`, `"h1"`, `"X"`, `"Z"`, `"p1"`, `"r1"`, etc.) which are not valid hexadecimal, so the PRD-faithful implementation correctly rejected them. The labels' only load-bearing property is equality/distinctness (dedup is keyed on hash equality); no test asserts on the echoed `content_hash`.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `ingest_document` (added `_as_hex` helper): deterministically hex-encodes each content-hash label's UTF-8 bytes before ingest. Identical labels → identical hex (same dedup bucket), distinct labels → distinct hex, every value valid hexadecimal per PRD §3.4. Single-point fix; all document ingestion routes through this one function.

**Fixes applied to `implementation/`:** None. The implementation's content_hash hex check is PRD-required and was left intact.

**Tests deleted:** None — every failing test passed STEP 1 (PRD verbatim-covers and uniquely determines the rule); the failure was a test-helper fixture inconsistency with the PRD, fixed in place.

**Orchestrator note:** The subagent's `results.*.json` did not persist after its exit (same artifact-persistence quirk seen with the earlier Step 5/6 interruption). The orchestrator independently re-ran the full 8-round parallel sweep to confirm and produce the artifacts: rounds 1–6 and 8 wrote 65/65; round 7's file failed to write under peak concurrent load and was re-run standalone → 65/65. Final: all 8 of `results.{1..8}.json` present, each 65/65, 0 failures.

## Step 8: Finalize PRD — 2026-06-05T18:20:19.000Z

PRD_FINALIZED.md created as a byte-for-byte copy of PRD.md, with **zero edits** — the sole Step 7 change was a pure fixture bug (`test_helpers/fixtures.py` hex-encoding of content-hash labels) with no PRD-silence or PRD/impl mismatch to pin.

**Line counts:** PRD.md = 284 lines, PRD_FINALIZED.md = 284 lines. Delta: 0 lines (0.0%). `diff` confirms identical.

**Rationale:** Fixes to implementation/: None. Tests deleted: None. The implementation's content_hash validation (`app.py:550-554`, non-empty + `^[0-9a-fA-F]+$` → ERR_INVALID_REQUEST) is already verbatim-covered by PRD §3.4 line 151 ("a non-empty hexadecimal `content_hash` used for duplicate detection"). No PRD silence, no PRD/impl mismatch.

**Pre-edit search log (one candidate considered, rejected):** Subject = content_hash field shape + dedup use. Enumerated paths: `app.py:547-566` (only validation/write site) and `services.py:212-238` (dedup by equality only, no re-validation). Both already consistent with PRD §3.4/§3.5 verbatim prose; adding any sentence would be redundant and risk narrowing the dedup path off-site. No edit committed (NO-NEW-MISMATCH rule).

## Step 9: Complete PRD — 2026-06-05T18:27:17.000Z

PRD_COMPLETED.md created from PRD_FINALIZED.md via full PRD-vs-implementation scan.

**Source vs completed:** PRD_FINALIZED.md = 284 lines / 38,688 chars; PRD_COMPLETED.md = 284 lines / 39,317 chars (+629 chars; all edits in-paragraph, no line-count change).

**Change counts:** 6 ambiguity-pins, 0 mismatch-revisions. Implementation and PRD were already tightly aligned; the only gaps were PRD *silence* on response-field shapes and sort tie-breaks.

**Per-change log:**
- §2.3 (Pagination) — insert — ambiguity — pinned list-sort tie-break: equal `created_at` resolved by ascending creation/insertion order — `helpers.py:61-63` (`sort_by_created` uses `(created_at, _seq)`).
- §3.3 (Spoliation Risk) — insert — ambiguity — pinned `/risk` read `data` shape to two integer fields `provisional_risk` and `final_risk` — `app.py:146-149`.
- §3.4 (Collection) — insert — ambiguity — pinned `/collection-summary` read `data` shape to two integer fields `estimate_total` and `actual_total` — `app.py:158-161`.
- §3.5 (Dedup) — insert — ambiguity — pinned dedup walk tie-break: equal `created_at` resolved by ascending creation/insertion order — `services.py:233`.
- §3.7 (Bates) — insert — ambiguity — pinned Bates allocation ordering tie-break: equal document `created_at` resolved by ascending document creation/insertion order — `services.py:267-274`.
- §3.9 (Clock) — insert — ambiguity — pinned `/_clock/set_current_utc` response to a `data` object with single field `now` (ISO 8601 UTC) — `app.py:1202`.

**Non-changes of note:** content_hash hex-only already pinned by §3.4/§2.8; VALIDATING never a resting state (PRD prose already says forks automatically); add_production_item has no set-state guard (PRD silent = impl silent, left unchanged); ProductionSet.version bumped by extra mutations but governed by §2.4 general rule. All 65 tests pass — alignment corroborated.

---

## Pipeline complete

All 9 steps finished. Final state: 65/65 tests pass across all 8 parallel rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (+6 ambiguity pins), implementation/ (11 files, in-memory Flask), test_helpers/ (9 files) + test_suite/ (5 files, 65 tests), results.{1..8}.json all green.
