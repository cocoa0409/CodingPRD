# Worklog — task_1328_provider_data_management_roster_ingestion

## Step 1: Create task directory — 2026-08-12T22:08:00.000Z

Pre-assigned by pipeline launcher: `tasks/task_1328_provider_data_management_roster_ingestion/` and its `workspace/` subdirectory already existed. No index scan performed; no other task_* directory touched. Difficulty target from user: "harder than expert level".

## Step 2: Generate scaffold — 2026-08-12T22:29:00.000Z

All checks pass. Final state of the deliverables:

**Files written** (all parse as valid YAML; `scaffold_lint.py` verdict: **clean lint**):

- `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Summary

**§1.1–§1.7 counts**
- Entities: 14 (RosterSource, RosterFile, RosterRow, Provider, ProviderAttribute, ProviderAlias, AttributeConflict, DistributionTarget, DistributionBatch, DistributionItem, AttestationCampaign, AttestationRequest, DataQualityScore, ProviderMergeRecord)
- State machines: 9 (RosterSource, RosterFile, RosterRow, Provider, ProviderAttribute, AttributeConflict, DistributionBatch, AttestationCampaign, AttestationRequest)
- Calculations: 6 (identity_resolution, attribute_effective_dating, conflicting_source_precedence, data_quality_scoring, attestation_escalation, distribution_snapshot_selection)
- Validations: 32 ordered rules
- Endpoints: 77
- Errors: 30
- Roles: 4 (IntakeOperator, DataSteward, DistributionOperator, ProviderContact — all opaque)
- Concurrency rules: 3 OCC rules (roster-file commit, provider merge, retro-approve)

**§1.8 difficulty instances**: 18 total, all non-stub, exactly 2 per rule × 9 rules, each with the rule-mandated differentiation (different entity domains for dual-variant, different modes (a)/(c) for combinatorial, different entities for non-linear machines, depth-3 + depth-2 cascades from different triggers, different error-category pairs, different metrics/endpoints for boundaries, different entity pairs for cross-entity deps, different interval semantics for overlap, different conserved quantities for compensating invariants).

**§1.9 corner instances**: 51 non-stub + 5 stub (`excluded_because` citing the §1.8 instance that already covers them), spanning all 9 guide sections: entities (7), state_machines (6), calculations (5), validations (11), endpoints (4), errors (12 incl. 5 stubs), rbac (4), complexity_layers (5), consistency_model (1).

**Design adjudications made**
1. **Archetype blend**: event sourcing (ingestion batches + append-only score/merge records) × compliance/audit (SoD, attestation SLAs). Role model = segregation_of_duties (registrar ≠ committer; committing operator ≠ conflict adjudicator).
2. **Difficulty-max choices per the harder-than-expert ask**: dual-variant identity resolution (FHIR strict vs default fuzzy), dual-variant quality scoring (stored vs DIRECTORY-strict eligibility), interval arithmetic with adjacency-vs-overlap vs retro-split variants, equal-rank source ties requiring manual adjudication with escalation blocked on ties, OCC on three write paths, threshold suspend at exactly 2 consecutive attestation expiries, snapshot selection using directory-strict score only for the DIRECTORY target.
3. **FK reverse-reachability**: first lint pass flagged 18 FK gaps; resolved by adding filtered-list params (roster-sources, providers, attribute-conflicts, distribution-batches), new standalone lists (roster-rows, provider-attributes, quality-scores), new single-resource GETs (attestation-campaigns/{id}, attestation-requests/{id}, quality-scores/{id}, provider-merges/{id}), and sub-resource lists (providers/{id}/distribution-items, providers/{id}/attestation-requests, providers/{id}/merge-records). Endpoint count rose 67 → 77.
4. **YAML quoting fixes**: list-indexed JSONPath captures (`$.data[0].field`) and `grounds:` entries containing `[...]` were quoted to parse under YAML flow syntax.
5. **Logical clock**: `POST /pdm/_clock/set_current_utc` test-driving endpoint with mandatory startup default 2026-08-01T00:00:00Z stated in its description; all SLA/effective-date arithmetic reads this clock.

## Step 3: Copy shared files — 2026-08-12T22:30:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1328_provider_data_management_roster_ingestion/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T22:51:00.000Z

All audits pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion/workspace/PRD.md` — 334 lines total.

### Section list with line counts
| Section | Lines | Span |
|---|---|---|
| §1 Introduction | 6 | 3–8 |
| §2 Global Specifications & System-Wide Principles (10 subsections) | 110 | 9–118 |
| §3 Business Logic & Workflows (9 subsections) | 96 | 119–214 |
| §4 Endpoint Definitions (77-row table) | 84 | 215–298 |
| §5 Error Code Catalogue (30-row table) | 36 | 299–334 |

§2 subsections: 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Request Evaluation Order, 2.7 Optimistic Concurrency Control, 2.8 Segregation of Duties in Stewardship, 2.9 Nested Resource Retrieval, 2.10 Dates/Integers/Rounding Discipline.
§3 subsections: 3.1 Upstream feed governance, 3.2 File intake pipeline, 3.3 Identity resolution, 3.4 Commit + effective-dated attribute timeline, 3.5 Cross-source conflict adjudication, 3.6 Provider lifecycle/aliases/merges, 3.7 Quality score, 3.8 Attestation outreach, 3.9 Distribution snapshots.

### Coverage audit (mechanical, scaffold-diffed)
- **Contract 1 Field coverage:** 93 required identifiers (all `entities[].fields`, all endpoint `input`/query params incl. `to_iso8601`, `expected_roster_file_version`, `expected_provider_version`, `as_of_date`, `min_quality_score`, `expired_count`, `expired_request_ids`) — 93 present in backticks, 0 missing. PASS.
- **Contract 3 §3 path purity:** 587 backtick tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.
- **Endpoints:** all 77 scaffold endpoints present in §4 with method, path, and role lists matching scaffold exactly (script-verified, 0 mismatches, 0 extras). Every `endpoints[].side_effects` rendered in §3 narratives.
- **Errors:** all 30 catalog errors present in §5 with matching HTTP statuses (script-verified); every error also named with its trigger condition in §2/§3 prose.
- **State machines:** all 9 machines covered — every from→to pair's states appear; preconditions paired with their error ids (inflight-file guard, row-count mismatch, unresolved conflicts, linkability, merge guards, quality floor, batch inflight/target disabled, campaign guards, attestation windows, precedence tie, replacement file); all side-effect cascades stated (commit write-through, merge rewiring, terminate close-out, suspend withdrawal, retry-supersede, file-reject per-stage row cascades).
- **Calculations:** all 6 rendered as precise prose (identity weights 50/30/20 with 70/100 thresholds + earliest-`created_at` tie-break + FHIR strict variant; half-open interval dating with supersede/truncate/zero-length/adjacency/retro-split rules; precedence-rank auto-resolution with created_at tie-breaks; quality components 40/30/20/10 with the 10 required keys and DIRECTORY double-escalation variant; inclusive second-expiry suspension threshold; snapshot eligibility/change-classification/ordering). No pseudocode operators, no interval-bracket notation, no fuzzy words (script-verified).
- **Validations:** all 32 priority entries expressed; explicit orderings stated for the global pipeline (§2.6) and for every multi-check endpoint — register (source-active before duplicate), parse (source-active before row-count), commit (state → SoD → OCC → unresolved-conflicts), merge (state → OCC → linkable → self-merge), resolve (SoD before missing-value), send (linkable → inflight → campaign-open), respond (window before payload), publish (inflight before target-disabled).
- **OCC:** 3/3 rules with write endpoint, `expected_*_version` field, mismatch rejection, exact `ERR_STALE_VERSION`/412 (§2.7), plus "endpoints not listed take no version field".
- **Roles:** all 4 named with exact spelling; all four `identity: opaque` translated into §2.1 prose incl. where the opaque id is recorded (file registrant, committer, `decided_by_user_id`).
- **Structured field content:** all rendered (empty-string npi/tin on unparseable, 0-based `row_index`, `reject_reason` iff `REJECTED`, null `term_date` = open-ended, `current_quality_score` 0 when never scored, bounds ≥1 / 0–100, append-only entities `updated_at`/`version` absent).

### Zero-Silence-Rule notes (places I had to make scaffold behavior fully explicit)
1. **File-reject from `VALIDATED`** — scaffold's only side effect is "no provider writes rolled back because none have occurred yet"; rendered exactly that, without inventing row-level effects.
2. **`SOURCE_RETIRED` reject reason** — rendered as a stated lasting consequence of retirement even though inflight guards make it rare in practice.
3. **Attestation-correction pseudo-source** — resolved the forward/backward reference: corrections carry the `roster_source_id` of the feed naming this campaign as its `default_attestation_campaign_id`, else the incumbent attribute's source.
4. **Future-dated attributes** — made explicit that they remain `PENDING` because no state-machine transition fires for them (the determinate reading; the scaffold lists no activation sweep).
5. **Suspend-vs-merge attestation withdrawal asymmetry** — suspension withdraws only `SENT` requests; a merge withdraws `DRAFT` and `SENT`; rendered distinctly in §3.6 and cross-referenced in §3.8.
6. **Survivor-not-ACTIVE merge guard** — scaffold assigns no error id to that precondition; mapped to the generic `ERR_INVALID_STATE` per the priority-4/31 state rule, preserving the global check order.
7. **Parse row-count mismatch** — stated both halves: the call fails with `ERR_ROW_COUNT_MISMATCH` (422) AND the file falls directly to `REJECTED` rather than `PARSED`.
8. **`AUTO_EXACT` link kind** — enum value defined as "system-resolved exact links" without inventing a creation path beyond what the scaffold specifies (only `AUTO_FUZZY`-at-commit and `MANUAL` creations are asserted).
9. **DIRECTORY scoring variant** — stated explicitly that the double-cost-escalated figure is used only for the eligibility check and never overwrites the stored provider score.

## Step 5: Generate unit tests — 2026-08-12T23:26:00.000Z

Generation complete. Summary:

## Totals
- **69 tests emitted** — Queue A (Difficulty): **26 tests covering 13 of 18 instances** (exactly 2 per instance); Queue B (Corner): **43 tests covering 43 of 48 non-stub instances** (1 each). All 5 `excluded_because` stubs were not translated; their `difficulty_instance` pointers all resolve.
- Every test's docstring ends with exactly one verbatim `Design:` tag (audited programmatically: no orphans, no dual tags), and every ≥8-word PRD quote in every docstring survives a literal grep of `PRD.md` (audited programmatically).

## Instances skipped (PRD-first filter)

**Queue A (5):**
- `dual_variant_calc/identity_resolution_strict_fhir_vs_default`, `transitive_cascade/commit_to_attribute_to_conflict_to_quality` — condition 2 (unique derivability): no PRD endpoint supplies roster-file row content (registration takes only `roster_source_id/external_file_ref/declared_row_count/checksum`), so a parsed row's npi/tin/location_key — and thus any MATCHED/CONFLICT outcome — cannot be deterministically controlled by a PRD-only implementer.
- `dual_variant_calc/data_quality_directory_strict_vs_stored_score`, `combinatorial_formula/quality_score_four_component_weighted_sum`, `combinatorial_formula/effective_dating_truncation_then_conflict_order` — condition 2: each requires an AttributeConflict (ESCALATED or OPEN), but conflicts arise only from overlapping intervals "from different roster sources," and manual attribute adds carry no client-selectable source (PRD assigns provenance only to "roster-originated" attributes), so no PRD path deterministically creates a conflict.

**Queue B (8):** `roster_row_system_fields_input_ignored`, `roster_row_reject_idempotency_second_reject_fails`, `identity_resolution_tie_break_created_at`, `commit_with_conflict_rows_blocked` — row-content non-controllability (condition 2). `conflicting_source_precedence_higher_rank_wins`, `conflict_resolution_merge_values_requires_value`, `escalate_equal_rank_conflict_rejected` — conflict-creation non-derivability (condition 2). `error_row_count_mismatch` — the materialized row count at parse is implementation-defined in the PRD, so a declared-vs-materialized mismatch cannot be forced (condition 2).

## Files
- `test_helpers/`: `__init__.py` (barrel), `types.py` (23 status/type enums + 14 TypedDicts; the 3 append-only record types omit `updated_at`/`version`), `api_client.py` (62 endpoint methods), `api_errors.py` (30 error ids + framework registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (clock, source/provider/attribute helpers, zero-row file pipeline to VALIDATED/COMMITTED with SoD-aware committer, distribution batch helpers, attestation send/expire/sweep/escalate chains, merge helper).
- `test_suite/`: `conftest.py` + 7 numbered files: `test_01_roster_source_governance.py` (7), `test_02_roster_file_pipeline.py` (9), `test_03_provider_lifecycle_and_quality.py` (15), `test_04_attribute_timeline.py` (8), `test_05_attestation_workflows.py` (16), `test_06_distribution_snapshots.py` (8), `test_07_security_and_rbac.py` (6).

## Notable translation decisions
- **Zero-row files are the only derivable pipeline input.** `declared_row_count=0` parses cleanly under any reasonable PRD reading; all file-pipeline fixtures use it. No test depends on parsed row content.
- **Recipe corrections (PRD wins over recipe):** (1) `attestation_request_cyclic_escalation`'s setup_api_calls contained only one request but asserted suspension at threshold 2 — I translated with two consecutive EXPIRED requests, and crucially did *not* escalate the first (an ESCALATED request blocks the second send via ERR_ATTESTATION_ALREADY_INFLIGHT); one test asserts expiries-without-escalation leave the provider ACTIVE, the other asserts the second escalation suspends. (2) `roster_file_parse_depends_on_source_active`'s recipe trigger (parse a REJECTED file) would yield ERR_INVALID_STATE, not the asserted error — translated to its actual assertion: registration against SUSPENDED and RETIRED sources → ERR_SOURCE_NOT_ACTIVE.
- **Simplified setups where evaluation order makes it faithful:** `distribution_operator_cannot_resolve_conflicts` uses a non-existent conflict id (authorization precedes existence per §2.6, so ERR_FORBIDDEN fires regardless). `roster_row_wrong_parent_returns_not_found` drops the recipe's parse call (irrelevant to the 404 assertion).
- **Distribution floor boundary** uses score 30 (the derivable fresh-provider score: 0+0+20+10) with floors 30/31 instead of the recipe's 70/69, since scores after manual attribute adds are non-derivable (freshness depends on the manual attributes' source, which the PRD leaves unspecified).
- **Dropped non-derivable sub-assertions:** `version == 1` on creation (PRD never states the initial version value) and `supersedes_attribute_id` on the retro split's right half (PRD's split paragraph doesn't name it).

## Step 6: Generate implementation — 2026-08-12T23:26:30.000Z

Implementation complete and verified. Here is the summary.

## File list under `implementation/`

```
implementation/
├── start.sh                  # launcher (executable)
├── requirements.txt          # flask>=2.0
├── app.py                    # Flask entry, ApiError + 404/405 handlers, blueprint registration
├── db.py                     # in-memory Store (14 empty dicts), LogicalClock (default 2026-08-01T00:00:00Z)
├── errors.py                 # ApiError + all 29 PRD error-id constants
├── response.py               # meta/response_type/data envelope, pagination (limit/offset/total_count/has_more)
├── middleware.py             # X-User-Role / X-User-ID auth, role gating, JSON body parsing
├── routes/
│   ├── clock.py              # POST /pdm/_clock/set_current_utc
│   ├── roster_sources.py     # CRUD + suspend/resume/retire + precedence-rank uniqueness
│   ├── roster_files.py       # register/parse/normalize/validate/commit/reject/supersede + row materialization
│   ├── roster_rows.py        # get/list + link/spawn-new/reject
│   ├── providers.py          # create/list/get + suspend/reinstate/terminate + nested listings
│   ├── attributes.py         # add/list/get/patch/approve-retro/void
│   ├── aliases.py            # list/unlink
│   ├── conflicts.py          # list/get/resolve/escalate
│   ├── distribution.py       # targets + batches + publish/ack/fail/discard + snapshot materialization
│   ├── attestation.py        # campaigns + requests + send/respond/escalate/withdraw/sweep
│   ├── quality.py            # quality-score list/recompute/get
│   └── merges.py             # provider-merges create/list/get
└── services/
    ├── common.py             # common-field minting (id/created_at/updated_at/version), ledger minting (id/created_at only), validation helpers
    ├── attributes.py         # attribute_effective_dating + conflicting_source_precedence
    ├── identity.py           # identity_resolution weighted scoring incl. FHIR strict variant
    └── quality.py            # data_quality_scoring (4 components), staleness flag, DIRECTORY strict variant
```

## Endpoint coverage: 77/77

Flask route table lists 78 routes; minus the built-in `/static/<path:filename>` = **77 API endpoints**, matching the PRD endpoint table exactly.

## State machines implemented

- **RosterSource** (ACTIVE/SUSPENDED/RETIRED) with inflight-file guard on suspend/retire, version increments.
- **RosterFile** (RECEIVED→PARSED→NORMALIZED→VALIDATED→COMMITTED, plus REJECTED from any pre-commit state with the per-state row cascades, SUPERSEDED from COMMITTED with replacement-file precondition). Row-count mismatch at parse → 422 + file drops to REJECTED.
- **RosterRow** (PENDING→MATCHED/NEW_PROVIDER/CONFLICT/REJECTED) incl. manual link with `ERR_PROVIDER_NOT_LINKABLE`, spawn-new from CONFLICT, manual reject with reason.
- **Provider** (ACTIVE→SUSPENDED/MERGED/TERMINATED) with SENT-request withdrawal on suspend, quality-floor gate on reinstate, SENT-attestation guard + open-ended attribute term-dating + auto-conflict-resolution on terminate.
- **ProviderAttribute** (PENDING→ACTIVE/RETRO_PENDING; RETRO_PENDING→ACTIVE via OCC-guarded approve / →VOIDED; ACTIVE→SUPERSEDED by interval rewrites).
- **AttributeConflict** (OPEN/ESCALATED→RESOLVED) with KEEP_INCUMBENT / ACCEPT_CHALLENGER / MERGE_VALUES side effects, tie-escalation block, SoD adjudicator check.
- **DistributionBatch** (BUILDING→PUBLISHED→ACKED/FAILED, FAILED→SUPERSEDED via retry, BUILDING→SUPERSEDED via discard) with inflight-batch and disabled-target guards.
- **AttestationCampaign** (DRAFT→OPEN→CLOSED, close blocked by SENT/ESCALATED, DRAFT requests withdrawn on close).
- **AttestationRequest** (DRAFT→SENT→RESPONDED/EXPIRED, EXPIRED→ESCALATED within one extra window, DRAFT→WITHDRAWN) with sweep, due-window enforcement, and 2nd-consecutive-expiry auto-suspend.

## Calculations implemented

- **identity_resolution** — 50/30/20 weighted legs, 70/100 thresholds, earliest-created_at tie-break, FHIR strict variant ([70,99]→CONFLICT, no AUTO_FUZZY).
- **attribute_effective_dating** — retro guard (RETRO_PENDING), future-dated stays PENDING, supersede/truncate/zero-length cleanup, adjacent-touch rule, retro-with-split variant; unit-verified in-process for all branches.
- **conflicting_source_precedence** — lower rank auto-wins (challenger VOIDED or incumbent SUPERSEDED), equal rank opens AttributeConflict with source-created_at tie-break for the incumbent slot.
- **data_quality_scoring** — completeness (round-half-up once at final multiplication via `Decimal`), freshness (6/fresh group, no-attribute groups stale), conflict (20−5/open), attestation (10−5/consecutive-unanswered); DIRECTORY variant counts ESCALATED double for eligibility only.
- **attestation_escalation** — consecutive-expiry counting stopping at RESPONDED/WITHDRAWN, inclusive ≥2 suspend threshold.
- **distribution_snapshot_selection** — ACTIVE + floor eligibility (plain score for CLAIMS/NETWORK, strict variant for DIRECTORY), ADD/UPDATE/TERM/QUALITY_DROP_EXCLUDED classification vs latest ACKED baseline, ordering by change-kind rank → npi ASC → provider created_at ASC.

## Validations

Full priority pipeline per PRD §2.6: auth (401) → RBAC (403) → left-to-right path existence (404) → state legality (409) → SoD (ERR_SOD_SAME_USER / ERR_SOD_ADJUDICATOR, 403) → OCC (`expected_roster_file_version` / `expected_provider_version`, 412) → business rules in declared order → syntactic body validation last (400). All 29 error IDs return their catalogued HTTP statuses.

## start.sh contract

- Guards dependency install: `pip install` runs only when `import flask` fails (per-test reboots are no-ops).
- `exec python3 app.py` keeps the server in the foreground with signal propagation.
- Binds `0.0.0.0`, port from `PORT` env var defaulting to 10000.
- Verified: two consecutive `bash start.sh` invocations boot within seconds with an empty store (`total_count: 0` on every list), confirming per-test-server isolation compatibility. No seeding anywhere — the store starts empty; all state is built via the API.

One note: the equal-rank AttributeConflict creation branch is unreachable end-to-end through the public API because `precedence_rank` uniqueness among non-RETIRED sources is enforced; I verified that branch (and the interval rewrite rules) in-process against the service layer instead.

## Step 7: Run tests and iterate — 2026-08-12T23:33:00.000Z

All 8 rounds passed cleanly: 69/69 tests, 0 failures, 0 errors, every round. The earlier "FAIL" listing was an artifact of my parser reading a nonexistent `outcome` key instead of `status` — no actual failures occurred. The suite is stable across the full parallel sweep; no diagnostics, deletions, or fixes were needed.

Summary:
- Iterations run: 1 (eight parallel rounds, all completed; 69/69 passed in each).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion` is already in a passing, non-flaky state.

Orchestrator verification: all 8 `results.{1..8}.json` files re-read after subagent exit — every round reports passed=69 total=69, 0 failures, 0 errors.

## Step 8: Finalize PRD — 2026-08-12T23:33:30.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — the skip condition is met; `PRD.md` already determines every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-12T23:52:00.000Z

All edits applied. Final verification passed. Here is the summary.

## Result

**Source vs completed:** `PRD.md` = 334 lines / 58,059 chars → `PRD_COMPLETED.md` = 334 lines / 65,844 chars (char-delta **+7,785**, zero lines added — all changes are in-paragraph inserts/revisions; no new sections). 30 paragraphs touched.

**Counts:** ~35 ambiguity-pins, 7 mismatch-revisions.

### Mismatch-revisions (PRD prose contradicted impl)
- **§2.6** — revise — mismatch — "syntactic body validation evaluated last" replaced with field-consumption-point semantics (creation endpoints validate body before business rules; transition endpoints like conflict-resolution validate after state/SoD/OCC) — `implementation/routes/roster_sources.py:37-47`, `implementation/routes/conflicts.py:60-76`
- **§3.2** — revise — mismatch — "reject_reason set iff status REJECTED" carved out for the file-level cascade from NORMALIZED/VALIDATED, which rejects PENDING/CONFLICT rows leaving `reject_reason` null (also pins that VALIDATED cascades rows identically to NORMALIZED) — `implementation/routes/roster_files.py:396-410`
- **§3.5** — revise — mismatch — incumbent-slot tie-break clause "when both intervals came from the same source" replaced (impl never opens same-source conflicts); tie-break is on equal source-registration instants — `implementation/services/attributes.py:99,120-128`
- **§3.6** — revise — mismatch — termination auto-resolves only `OPEN` conflicts (ESCALATED untouched) and term-dates only intervals in ACTIVE/PENDING/RETRO_PENDING — `implementation/routes/providers.py:147-157`
- **§3.6** — revise — mismatch — merge re-points attribute `provider_id` *without* re-running dating-rule re-resolution (PRD claimed re-resolution) — `implementation/routes/merges.py:62-65`
- **§3.7** — revise — mismatch — recompute trigger list now includes attestation-request escalation, which impl scores but PRD omitted — `implementation/routes/attestation.py:325`
- **§3.9** — revise — mismatch — item ordering: materialization order (change-kind rank, npi, created_at) kept, but the "never by id" claim replaced — listings follow §2.3 ordering and a batch's items share one logical instant, so they list in `id` order — `implementation/routes/distribution.py:227-238`, `implementation/response.py:77`

### Ambiguity-pins (PRD silent; pinned to impl)
- **§2.1** — `X-User-ID` never required/validated; only `X-User-Role` gates auth — `middleware.py:11-29`
- **§2.3** — `id` ascending tie-break on equal `created_at` — `response.py:77`
- **§2.5** — `version` starts at 1; `updated_at`==`created_at` at creation — `services/common.py:10-13`
- **§2.7** — missing/non-integer `expected_*_version` → `ERR_INVALID_REQUEST` at the OCC step (before unresolved-rows on commit) — `roster_files.py:302-308`
- **§2.9** — unknown route/method → `ERR_NOT_FOUND` 404 envelope — `app.py:18-27`
- **§3.1** — `default_attestation_campaign_id` recorded without existence check; patch with non-mutable field → `ERR_INVALID_REQUEST` — `roster_sources.py:42-44,96-98`
- **§3.2** — optional `payload_rows` registration field; parse materializes per-entry rows (non-strings JSON-serialized) else `declared_row_count` synthetic `row_{i}` rows — `roster_files.py:85,124-141`
- **§3.2** — normalization mechanics: digit-stripping coercion, verbatim-or-16-hex-SHA-256 `location_key`, `effective_date` defaults to logical clock date, non-JSON line behavior, `attributes` payload shape — `roster_files.py:163-206`, `269-287`
- **§3.2** — manual row-reject reason must be one of the five enums (else 400); file `rejected_row_count` recomputed — `roster_rows.py:101-123`
- **§3.3** — `created_at` tie-break applies only within the 70-99 band when no perfect scorer exists; ≥2 perfect scorers → CONFLICT with no tie-break under both FHIR and non-FHIR — `services/identity.py:57-97`
- **§3.3** — commit records an alias for every MATCHED row (AUTO_EXACT confidence 100; AUTO_FUZZY winning score; MANUAL 100, on top of the link-time alias → two MANUAL aliases for manually linked rows); manual link alias carries confidence 100; within-file row listing accepts `status` — `roster_files.py:342-354`, `roster_rows.py:53-87`, `roster_files.py:441-443`
- **§3.4** — retro guard compares against the earliest effective date among ACTIVE **or PENDING** intervals — `services/attributes.py:70-80`
- **§3.4** — approve-retro applies rewrite rules directly (no retro re-fire, no precedence adjudication); future-dated approval stays PENDING — `routes/attributes.py:178-249`
- **§3.4** — `as_of_date` semantics (eff ≤ as_of < term, null term = open); patch may target any status and re-opens terminal attributes via PENDING reset — `routes/attributes.py:84-90,122-150`
- **§3.5** — precedence adjudication runs after retro guard/future check and before rewrites, and only for different-source, different-value overlaps (same-source, equal-value, and source-less intervals use ordinary rewrite rules) — `services/attributes.py:92-103`
- **§3.5** — missing/empty `resolution_reason` → 400; MERGE_VALUES merged attribute inherits challenger's `roster_source_id`, open-ended term, supersedes challenger, born ACTIVE — `routes/conflicts.py:72-76,94-114`
- **§3.6** — npi/triple uniqueness violations → `ERR_INVALID_REQUEST` (triple unique across all providers incl. MERGED); reinstate gate inapplicable when no ACTIVE targets; merge guard preamble (body-field 400s and provider 404s precede survivor state check); "open conflicts" transferred = OPEN+ESCALATED — `providers.py:37-42,119-128`, `merges.py:26-49,72-75`
- **§3.7** — group whose freshest ACTIVE attribute has no roster source counts as fresh (component and staleness_flag); attestation scan skips in-flight SENT without breaking the count, `created_at` breaks `sent_at` ties — `services/quality.py:44-45,74-92`
- **§3.8** — request creation needs only campaign/provider existence (campaign need not be OPEN); `corrected_payload` keys are `GROUP.attribute_key`, bare keys → DEMOGRAPHIC, object values ignored; escalation suspension scan mirrors the SENT-skip rule — `attestation.py:126-131,259-267,309-320`
- **§3.9** — batch creation: unknown target/`retry_of_batch_id` → 404, target need not be ACTIVE, non-FAILED retry target recorded as lineage untouched; eligibility evaluated at publish time; baseline membership excludes QUALITY_DROP_EXCLUDED items; SUSPENDED baseline provider yields no item; `payload_hash` = SHA-256 of `npi|tin|location_key|current_quality_score`; `fail` requires non-empty reason (else 400) — `distribution.py:92-114,151-156,193-223,262-265`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1328_provider_data_management_roster_ingestion/workspace/PRD_COMPLETED.md`
