# Worklog — task_1430_annuity_1035_exchange_replacement_review

## Step 1: Create Task Directory — 2026-08-13T06:23:00.000Z

Task directory `tasks/task_1430_annuity_1035_exchange_replacement_review/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. No index scan performed.

## Step 2: Generate Scaffold — 2026-08-13T07:20:00.000Z

Scaffold generation complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/`, and the final lint verdict is clean:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**What was built** (compliance/audit archetype + workflow orchestration, flat topology, segregation-of-duties role model):

- **SCAFFOLD.yaml** — 9 entities (Producer, Client, ExistingContract, ExchangeCase, CaseDocument, ComparisonAnalysis, FundsTransfer, ReviewDecision, ActivityEvent), 5 state machines (branching ExchangeCase with INFO_REQUESTED revert cycle and FUNDS_REQUESTED→APPROVED compensation edge; cyclic CaseDocument revision loop; cascaded FundsTransfer/ExistingContract machines; auto-flag/auto-clear Producer machine), 1 OCC concurrency rule (`analysis-create-stale-case`, 412 on stale `expected_case_version`), 7 calculations, 18 ordered validations, 35 endpoints (including `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default), 21 error codes, 6 roles with entity_backed Producer identity.

- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 19 instances (≥2 per rule): dual-variant surrender charge (300 vs 200 bps across the 45-day settlement lag) and churn rate (10000 vs 5000 bps by denominator); three combinatorial modes (b: pinned multiply-then-divide basis allocation = 2,666,666; c: pinned charge→received→bonus order giving net cost 2,102,000; a: nested min/max rider-loss cap at 20,000,000); cyclic machines on two entities; a depth-4 rescission cascade and a depth-3 funds-receipt cascade; priority pairs (state vs safety; safety vs fiscal); inclusive boundaries (free-look deadline date, partial-amount-equals-value); cross-entity guards on Case→Contract and Document→Case; occupation vs cooling-off-gap interval semantics; tax-basis and account-value conservation invariants.

- **SCAFFOLD_CORNER_DESIGN.yaml** — 42 active corner instances + 15 excluded_because stubs across all nine claim-extraction sections, including OCC stale/fresh retry, churn flag set at exact inclusive thresholds then auto-clear via window age-out, half-open 365-day window boundary, anniversary-boundary and beyond-schedule surrender charges, break-even sentinel 99, senior/junior free-look split, five RBAC denials, and a full error-catalog coverage map.

All formula-derived asserts were pre-computed and verified with Python (surrender bands, basis floor arithmetic, bonus/net-cost ordering, break_even_years == 2, all deadline dates). Every `${var}` traces to an earlier `captures:`, all negative triggers capture `$.data.error_id` or match negative-name patterns, and all 21 error codes are exercised by at least one instance.

## Step 3: Copy Shared Files — 2026-08-13T07:21:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:35:00.000Z

Done. Generated `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/PRD.md` from the scaffold, per the prd-bench-doc-generator skill. The two forbidden difficulty/corner design files were not opened.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs — churning/conduct-risk business context + system scope)
- §2 nine subsections: RBAC with per-role identity semantics (Producer entity-backed, five opaque roles named individually), the verbatim §2.2 response-envelope block, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default 2026-08-01T00:00:00Z, never wall-clock, churn re-evaluation side effect), resource identity/versioning (including `updated_at`/`version` absent on ReviewDecision and ActivityEvent), integer-cents/bps/floor-division conventions, OCC (`expected_case_version` → `ERR_STALE_VERSION` 412, no other endpoint takes a version), the seven-rung validation precedence ladder, and the two audit record types
- §3 eight subsections organized by case lifecycle: book-of-business setup, submission gates (explicit seven-step ordering), document review loop, comparison analysis (both surrender-charge variants, pinned net-cost order, multiply-then-divide basis allocation with the 2,666,666 vs 2,666,400 worked example, year-by-year break-even with 99 sentinel), two-stage review with duty segregation, funds movement with compensation path, free-look/completion/rescission with the transitive restore chain, and producer churn surveillance (half-open 365-day window, inclusive 2-completion/5,000-bps thresholds)
- §4 endpoint table: 35 rows, 4 columns only; §5 error catalogue: 21 rows, 2 columns only

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 82 required, 82 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: global ladder + submit's 7-gate order + recommend docs-before-analysis + state-before-OCC all expressed, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (analysis create + expected_case_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 28 checked (16 case + 3 document + 3 transfer + 4 contract + 4 producer... all 5 machines), 28 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (no pseudocode, no fuzzy words — grep-verified), 0 missing
- validations[] conditions: 18 checked, 18 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (submit chains, transfer cascades, rescission restore, supersession, clock re-evaluation), 0 missing
- entities[].fields[] structured content: defaults, initial states, null-until semantics, common_fields:false carve-out all reconstructible, 0 missing
- sibling-branch symmetry: FULL/PARTIAL, today/at-settlement, completed/submitted rate variants, dual reject stages — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 340
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification (scripted): all 21 error IDs present in prose, all enum/state values present (13 case states, 3 contract/document/transfer/producer states, doc types, stages, decisions, 9 event types), all 11 calculation constants embedded in business context, all 6 role names exact, endpoint table paths/methods match scaffold 35/35 with no extras.

## Step 6: Generate Implementation — 2026-08-13T08:00:00.000Z

Implementation complete and verified. Summary:

## Implementation Complete

Generated a Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/implementation/` with:

**Files:**
- `start.sh` — executable launcher with guarded `pip install` (skipped when flask is already importable), `exec python3 app.py` in foreground
- `requirements.txt` — Flask only
- `app.py` — Flask entrypoint, binds `0.0.0.0:$PORT` (default 10000), registers blueprints, central `ApiError` handler, 404/405 fallback
- `db.py` — In-memory dict stores (producers, clients, contracts, cases, documents, analyses, transfers, review_decisions, activity_events), logical clock starting at `2026-08-01T00:00:00Z`, ISO-8601 helpers (3-fractional-digit UTC), UUID minting. **No seeding.**
- `errors.py` — All 21 error IDs from SCAFFOLD §1.6 with HTTP statuses
- `response.py` — Envelope `{meta:{api_request_id, api_request_timestamp, ...}, response_type, data}`; list responses add `limit/offset/total_count/has_more` to meta
- `middleware.py` — `X-User-ID` + `X-User-Role` extraction; the 6 declared roles; 400 on missing/invalid, 403 on role-not-allowed
- `services/calculations.py` — Surrender schedule (chronological + at_settlement variants, inclusive anniversary arithmetic), tax basis multiply-then-divide, benefit loss with 2,000,000-cent cap, net_replacement_cost pinned order, break_even_years (year-by-year compounding, sentinel 99), free_look deadline (30 senior / 20 standard, day-0 = delivery)
- `services/churn.py` — Rolling 365-day half-open window counters, completed/submitted bps variants, inclusive threshold flagging (completed>=2 AND rate>=5000), PRODUCER_FLAGGED/UNFLAGGED events
- `services/serializers.py` — Field-exact entity views; audit records (ActivityEvent, ReviewDecision) omit `updated_at`/`version` per PRD §2.5
- `routes/{clock,producers,clients,contracts,cases,documents,transfers}.py` — All 35 endpoints from SCAFFOLD §1.5 with role guards, validation ladder ordering (auth → role → existence → ownership → body shape → state → OCC → business), state machine transitions with cascading side effects (request_funds → SURRENDER_PENDING, mark_received → FUNDS_RECEIVED + EXCHANGED with value/basis reduction, mark_failed → APPROVED + IN_FORCE revert, rescind → RESCINDED + RETURNED + IN_FORCE restore from pre_exchange snapshots + client stamp)

**Verified by smoke tests:**
- Full lifecycle DRAFT → SUBMITTED → SUITABILITY_REVIEW → PENDING_PRINCIPAL → APPROVED → FUNDS_REQUESTED → FUNDS_RECEIVED → IN_FREE_LOOK → COMPLETED
- Analysis calculations: at_settlement charge, bonus on net received, benefit loss capped, pro-rata basis `8,000,000 × 3,333,333 / 10,000,000 = 2,666,666` (multiply-then-divide)
- Rescission cascade restores contract snapshots, sets client.last_rescinded_at, bumps versions
- OCC 412 on stale `expected_case_version`
- Submission gates: PARTIAL below min (409), PARTIAL ≥ account value (409), cooling-off (409), contract not in force (409)
- Senior (30d) vs standard (20d) free-look deadlines
- Server boots cleanly from fresh process via `bash start.sh`

## Step 5: Generate Unit Tests — 2026-08-13T08:20:00.000Z

All checks pass. The generated suite is complete and verified.

## Report

**Generated for** `tasks/task_1430_annuity_1035_exchange_replacement_review/`:

**`test_helpers/` (9 modules)** — PRD-specific infrastructure, all importing framework generics from `prd_bench_local_runner.testing`:
- `types.py` — 6 roles, 9 status/type enums, 9 entity TypedDicts; audit records (`ReviewDecision`, `ActivityEvent`) correctly modeled with only `id` + `created_at` (no `updated_at`/`version`, per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 35 PRD §4 endpoints
- `api_errors.py` — all 21 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus `assert_logical_instant` (parse-compares logical-clock instants, format-agnostic) and `assert_basis_conservation`
- `factories.py`, `constants.py` (all PRD thresholds: 45d settlement lag, 100,000 min partial, 2,000,000 rider cap, 20/30 free-look, churn 2/5000 bps/365d/30d), `test_users.py` (opaque-role constants + mandatory `make_producer_headers(id)` builder for the entity-backed Producer role)
- `fixtures.py` — composite pipelines: `setup_case_in_review` → `_pending_principal` → `_approved` → `_in_free_look` → `_completed`/`_rescinded`, with OCC version capture and identity-threaded producer headers

**`test_suite/` (conftest + 9 files, 80 tests)** — all collected cleanly by pytest:
- Queue A: all 19 difficulty instances × ≥2 tests = 38 tests
- Queue B: 41 of 42 non-stub corner instances × ≥1 test
- Automated audit confirmed: every test docstring ends with exactly one verbatim `Design:` tag resolving to a real instance, and every ≥6-word quoted PRD citation survives a whitespace-normalized literal grep of PRD.md

**Deliberate skip (1 instance, gap left as gap):** `Corner/entities/producer_system_field_rejected_as_invalid_request` — asserts a client-supplied `status` field on POST /producers is rejected with `ERR_INVALID_REQUEST`. PRD §3.1's malformed-payload sentence enumerates only missing required fields, out-of-set enums, non-positive integers, and non-ascending surrender schedules; it never states unknown/system fields are rejected, so a faithful PRD-only implementer could ignore the extra key. Fails unique derivability — no test emitted, no placeholder.

**Design-index bug worked around:** `benefit_loss_cap_branch` (§1.8) pre-computes `benefit_loss_cents == 20000000` and `net == 20102000`, contradicting the PRD's verbatim rule "floored at zero and capped at 2,000,000 cents" (and the scaffold's own `RIDER_LOSS_CAP_CENTS: 2000000`). The emitted tests assert the PRD-derived values (2,000,000 and 2,102,000), since the PRD is the contract under test.

**Audit trail:** all 15 `excluded_because:` stub cross-references resolve to real difficulty instances; no `skip`/`xfail` markers; no scaffold/section leakage in generated comments.

## Step 7: Run Tests and Iterate — 2026-08-13T08:45:00.000Z

Clean 8-round sweep achieved. Summary below.

## Summary

**Iterations run: 4** (sweep 1 → diagnosis + 2 fixes → sweep 2 confirmed fixes, infrastructure flake → sweep 3 re-confirmed zero assertion failures → sweep 4 fully clean: 80/80 × 8 rounds, 640/640 tests).

**Tests deleted: none.** Every failing assertion traced to a verbatim PRD sentence with unique derivability; no test-helper changes were needed.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `test_suite/`: none.**

**Fixes applied to `implementation/` (2):**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/implementation/routes/cases.py` — added the missing `ERR_DOCUMENT_LOCKED` import. `submit_document` (line ~674) raised the constant without importing it, so the PRD §3.3 "resubmitting a VERIFIED `doc_type` is rejected with `ERR_DOCUMENT_LOCKED`" path died with a NameError → HTTP 500 `ERR_INTERNAL`. This was the deterministic failure of `test_verified_document_type_locked_against_resubmission` in all 8 rounds of sweep 1.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/implementation/routes/common.py` — `apply_pagination` sorted by `(created_at, id)`; the random-UUID tiebreak scrambled creation order whenever the fixed logical clock produced timestamp ties (which is always, absent a clock-set). PRD §2.3 mandates sorting by `created_at` ascending only; Python's stable sort preserves insertion (creation) order among ties, which is what the audit-trail tests assert. This was the flaky failure of `test_suspend_reinstate_cycle_with_audit_events` (event order `PRODUCER_SUSPENDED`/`PRODUCER_REINSTATED` randomized) and `test_info_request_cycle_completes_fork_to_approval` (review-decision order randomized) across rounds.

**Non-bug flakes observed (no action taken, none attributable to test or implementation):** sweeps 2 and 3 each had 1–4 tests error with "could not be restarted" / 30s setup timeouts — transient server-boot stalls caused by ~15 co-tenant pipeline agents running their own 8-round sweeps on the shared host (idle boot measured at ~600ms; stalls exceeded 30s only during cross-agent load spikes). The runner's restart poll was also externally widened from 15s to ~30s mid-session. Sweep 4 ran the identical code with zero errors, confirming the two fixes above resolved all genuine failures.

## Step 8: Finalize PRD — 2026-08-13T09:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/PRD_FINALIZED.md` produced.

**Line counts / %-delta:** PRD.md 248 lines, PRD_FINALIZED.md 248 lines (0% line-count delta; the single change is an in-place sentence extension on line 72, +131 characters).

**Changes:**

- **§2.3 Pagination — revise — appended "No secondary sort key is applied: records that share the same `created_at` keep their relative creation order (the sort is stable)." — `implementation/routes/common.py:53`** (`apply_pagination` sorts by `created_at` only via Python's stable `sorted`; ties retain insertion/creation order). PRD §2.3 previously pinned only the primary key, leaving tie order open — a fresh implementer adding an `id` tiebreak (as the pre-fix implementation did) would scramble audit-trail ordering whenever the logical clock produces timestamp ties. This was Step 7 fix #2.

**Step 7 fix #1 (`ERR_DOCUMENT_LOCKED` import in `routes/cases.py:15/675`) required no PRD edit:** it was a pure implementation bug (missing import → NameError → HTTP 500). PRD §3.3 already uniquely pins the behavior verbatim ("resubmitting that `doc_type` is rejected with `ERR_DOCUMENT_LOCKED` (HTTP 409)"), and the post-fix implementation matches it exactly. Prose kept verbatim per method rule 2.

**Per-edit pre-edit search log:**

- Edit 1 (§2.3 tie-break sentence):
  - (a) **Subject:** ordering of results returned by paginated list endpoints.
  - (b) **Paths enumerated:** `routes/common.py:45-56` (`apply_pagination` — the sole sorting site in the codebase); all 8 call sites read — `routes/clients.py:71` (client contracts), `routes/cases.py:215` (cases), `routes/cases.py:728` (documents), `routes/cases.py:825` (comparison-analyses), `routes/cases.py:842` (funds-transfers), `routes/cases.py:859` (case activity-events), `routes/cases.py:872` (review-decisions), `routes/producers.py:118` (producer activity-events). Grepped `sorted(|.sort(|sort_by|order_by|key=` across all of `implementation/`: the only other hit is `common.py:103` (enum values inside an error-message string, not list ordering). Verified via `services/churn.py:27-28` and `services/serializers.py:150-172` that activity events and review decisions carry `created_at` (events set `created_at = event_at`), so every list fed to `apply_pagination` has the sort key; backing stores are insertion-ordered (lists for audit records, insertion-ordered dicts for entities), so stable sort = creation order among ties at every call site.
  - (c) **Wording adjustment:** none needed after enumeration — the sentence was deliberately scoped to tie behavior only ("No secondary sort key is applied... ties keep relative creation order"), leaving the existing primary-key sentence untouched and making no claim about non-paginated payloads (e.g., the client-supplied ordering of `surrender_schedule`, which the server never sorts). Consistent with all 8 enumerated call sites.

## Step 9: Complete PRD — 2026-08-13T09:30:00.000Z

The diff is complete and every pinned claim was verified against the implementation source. Final summary:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1430_annuity_1035_exchange_replacement_review/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` 248 lines / 36,713 chars → `PRD_COMPLETED.md` 251 lines / 40,622 chars (char-delta +3,909). 15 edit sites, all in-paragraph inserts/revisions; no new sections.

**Counts:** 11 ambiguity-pins, 4 mismatch-revisions.

### Changes

- §2.2 — insert — ambiguity — undefined paths/unsupported methods → `ERR_NOT_FOUND` (404); unexpected failures → `ERR_INTERNAL` (500) in same envelope — `implementation/app.py:36-61`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` = `offset + page_size < total_count` — `implementation/routes/common.py:26-42`, `implementation/response.py:27`
- §2.4 — insert — ambiguity — unparseable `to_iso8601` → `ERR_INVALID_REQUEST`; any parseable instant accepted, forward or backward — `implementation/routes/clock.py:18-24`
- §2.5 — insert — mismatch — blanket "version increments on every mutation" carved out: producer counter recompute and `last_churn_eval_at` stamping do not bump `version`/`updated_at`; producer version moves only on suspend/reinstate/flag transitions — `implementation/services/churn.py:38-98`
- §2.8 — revise — mismatch — creation endpoints (`POST /producers|/clients|/contracts|/cases`) validate body shape before FK existence (and before ownership on `POST /cases`); analysis creation checks state before body shape — `implementation/routes/cases.py:118-157,743-763`, `implementation/routes/contracts.py:56-99`
- §3.1 — insert — ambiguity — `license_number` uniqueness is exact/case-sensitive, collision → `ERR_INVALID_REQUEST` (400); state codes stored as supplied (non-empty string only) — `implementation/routes/producers.py:32-41`
- §3.1 — insert — ambiguity — `age_years`/`is_senior` computed once at registration, stored, never recomputed — `implementation/routes/clients.py:34-45`
- §3.1 — revise — ambiguity — contract constraints: `account_value_cents` positive, `tax_basis_cents` non-negative, schedule non-empty with years exactly consecutive 1..N (no gaps), `living_benefit_rider` required boolean, rider amount/fee optional non-negative (fee ≤ 10,000) defaulting to 0 whenever omitted, `last_exchange_completed_at` non-empty string unparsed at registration; unparseable ISO date added to malformed-payload list — `implementation/routes/contracts.py:22-99`
- §3.2 — insert — ambiguity — `producer_id` ≠ `X-User-ID` → `ERR_CASE_NOT_OWNED_BY_PRODUCER`; `new_product_surrender_years` non-negative int; bonus/fee bps optional ints in [0, 10000]; PARTIAL `exchange_amount_cents` must be positive int at creation — `implementation/routes/cases.py:120-157`
- §3.3 — revise+insert — ambiguity — adjudicating a non-`SUBMITTED` document → `ERR_INVALID_STATE_TRANSITION`; only a `REJECTED` doc is reopened in place (fresh revision-1 doc created even if a `SUBMITTED` one of same type exists); any successful submission while `INFO_REQUESTED` returns case to `SUITABILITY_REVIEW`; 201 on both submit and resubmit; `request_info` requires `rationale` — `implementation/routes/cases.py:655-713,360`, `implementation/routes/documents.py:23-72`
- §3.4 — insert — ambiguity — state check precedes body validation and version check; `expected_case_version` non-negative int; growth assumptions unrestricted ints (negatives accepted); Feb-29 issues observe Feb 28 anniversary in non-leap years — `implementation/routes/cases.py:743-763`, `implementation/services/calculations.py:40-44`
- §3.7 — revise — mismatch — free-look length uses the client's stored registration-time `is_senior`, not age recomputed at delivery — `implementation/routes/cases.py:549-552`, `implementation/services/calculations.py:166-175`
- §3.8 — revise — mismatch — full evaluation (with `last_churn_eval_at` stamping and flag toggling) runs only after submission/completion/rescission/reinstatement/clock-set; rejection and withdrawal recompute counters/rates only — `implementation/services/churn.py:76-103`, `implementation/routes/cases.py:336,445`
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row — `implementation/app.py:52-61`

Everything else in the implementation (all 32 endpoints, role lists, gate orderings in §3.2, OCC semantics, all §3.4 formulas including the multiply-then-divide basis allocation and year-by-year break-even, funds-transfer cascades, rescission restore chain, churn window/thresholds) was already uniquely pinned by the PRD and left untouched.
