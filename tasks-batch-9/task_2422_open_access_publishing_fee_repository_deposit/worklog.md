# Worklog — task_2422_open_access_publishing_fee_repository_deposit

## Step 1: Create task directory — 2026-09-02T15:54:57.395Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2422_open_access_publishing_fee_repository_deposit` and its `workspace/` subdirectory. Index fixed by scenario number (2422) per orchestrator instruction; no auto-allocation scan performed.

## Step 2: Generate scaffold — 2026-09-02T17:21:17.524Z

Task 2422 scaffold is complete — all three artifacts written and the linter is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2422_open_access_publishing_fee_repository_deposit/`)
- `SCAFFOLD.yaml` — 2661 lines, top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1800 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3702 lines, single key `scaffold_corner_design`

**§1.0–§1.7 counts**: 14 entities (Publisher, Journal, TransformativeAgreement, AgreementCoverage, Author, Funder, Grant, Article, EligibilityDetermination, APCFund, FundRequest, FundAllocation, PublisherInvoice, RepositoryDeposit) · 55 endpoints · 8 calculations · 34 ordered validations · 45 error codes · 5 roles (AgreementAdmin, ScholCommLibrarian, FundManager, RepositoryCurator, CorrespondingAuthor) · 2 OCC rules · profile: `quota_allocation` × `compliance_audit`, graph topology, parallel state machine (Article funding × compliance dimensions), segregation-of-duties role model, immediate consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

**§1.8** — 9 rule_ids × 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9** — all nine guide sections, 81 instances (57 full recipes + 24 `excluded_because` stubs citing the §1.8 instance that already covers the corner): entities 13 (11+2), state_machines 15 (12+3), calculations 14 (8+6), validations 11 (5+6), endpoints 6, errors 8, rbac 4, cross_cutting_complexity_layers 9 (2+7), consistency_model 1. Every one of the 45 error codes is triggerable across §1.8 + §1.9; instance names are unique across both design files; no forbidden concurrency vocabulary.

**Final lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task-dir>`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2422_open_access_publishing_fee_repository_deposit/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2422_open_access_publishing_fee_repository_deposit/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2422_open_access_publishing_fee_repository_deposit/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  754

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied while finishing the last sections: swapped a non-existent `GET /publishers` collection call for `GET /publishers/{id}/journals` in the pagination-bounds corner; corrected two `funding_status` asserts to the declared initial `DRAFT` / `SELF_FUNDED` (AUTHOR_PAYS) values; replaced a literal `expected_publisher_version: "1"` with a captured `${...}` per lint rule (e). The hard constraint was respected — no sibling `task_*/` directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-02T17:21:17.524Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:35:29.239Z

PRD generation complete.

**Deliverable:** `workspace/PRD.md`

- **Final line count: 449** (subagent reported 450 incl. trailing newline)
- **Last heading: `## 5. Error Code Catalogue`** — file ends at a real boundary, on the final error-table row (`| ERR_AUTHOR_CAP_EXHAUSTED | 422 |`), single trailing newline, no mid-sentence cut. Orchestrator independently verified the tail and the full heading list (§1 → §5, 33 headings): NOT truncated.
- Temporary verification helper `workspace/_check.py` was deleted; the folder now holds only `INSTRUCTION.md` and `PRD.md`.
- The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Hard Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 139 required / 139 present / 0 missing
- `endpoints[].request_body` (incl. output keys): 92 required / 92 present / 0 missing
- `endpoints[].query_params`: 25 required / 25 present / 0 missing
- Union: 163 required / 163 present / **0 missing** (441 distinct backticked tokens in the document)

**Hard Contract 2 — Rule Coverage: PASS**
- All 34 validations appear as a numbered, priority-ordered list in §2.11, each with its translated check, error id, HTTP status, and full `applies_to` endpoint enumeration.
- All 8 calculations are transcribed with every named constant, threshold, tier boundary, rounding step and pinned evaluation order (`FUND_FREEZE_THRESHOLD_PCT` 0.98, `VARIANCE_TOLERANCE_CENTS` 100, `DISCOUNT_EPSILON` 0.0001, volume tiers 500000/2000000/5000000 → 0.10/0.15/0.20, screening weights 25/15/20/cap 25/multiplier 5/15/threshold 14 days/credit 0.1, bands 85/60/35).
- All 7 state machines: every transition, guard and terminal state; 0 state values missing from the checker sweep. Parallel Article dimensions (`funding_status` × `compliance_status`) are described as mutually non-reading.
- Both OCC rules (`expected_publisher_version`, `expected_article_version` → `ERR_STALE_PARENT_VERSION`, 412) in §2.6.
- All 5 roles named and characterized in §2.1, including `CorrespondingAuthor` as `entity_backed:Author` versus the four opaque roles, plus the 7 ownership-checked operations.
- All 46 error ids present in prose/tables; 0 missing.
- All entity enum values present; 0 missing.

**Hard Contract 3 — §3 Path Purity: PASS**
- 947 backticked tokens scanned inside §3: **0 violations** — no `/`-prefixed tokens, no bare HTTP method tokens, no method+path pairs. All path-bearing `applies_to` scopes were deliberately routed into §2.11 and §4 instead.

**Structural completeness:** 14 entities (incl. `AgreementCoverage` and `EligibilityDetermination` explicitly noted as carrying only `id` and `created_at`), §4 endpoint table with exactly **55 rows** (Method / Path / Description / Authorized Role(s)), §5 error table with exactly **46 rows** sorted by status, and §2.2 pasted byte-verbatim from `section-2.2-response-structure.md`.

## Step 5: Generate unit tests — 2026-09-02T18:17:33.259Z

Stage 2 is complete and audited. Final state:

## Files written

**Stage 1 — `test_helpers/`** (9 files): `__init__.py` (barrel), `types.py` (25 enums + 14 entity TypedDicts; `AgreementCoverage`/`EligibilityDetermination` omit `updated_at`/`version`), `api_client.py` (`ApiClient` with one method per PRD endpoint + `api_client` singleton), `api_errors.py` (all 45 error IDs + status map registered via `set_error_http_status_map`), `constants.py`, `test_users.py` (5 roles + mandatory `make_corresponding_author_headers`), `factories.py` (23 payload factories), `assertions.py` (per-entity + ledger/pricing/DOI/PID invariants), `fixtures.py` (single-step helpers + 9 composites).

**Stage 2 — `test_suite/`**: `conftest.py` + 18 numbered files `test_01_…` through `test_18_…`.

## Test counts

- **Queue A (Difficulty)**: 36 tests across `test_01`–`test_09` — exactly 2 per instance for all 18 instances.
- **Queue B (Corner)**: 61 tests across `test_10`–`test_18` — ≥1 for each of the 57 non-stub instances (parametrized families for the 13 not-found codes, 5 uniqueness codes, pagination bounds, rejected roles).
- **97 test functions → 117 collected test ids**, `--collect-only` clean, `compileall` clean.

## Skipped instances

**None.** All 18 difficulty and all 57 non-stub corner instances passed the PRD-first two-condition filter — this PRD is unusually explicit (§2.11 fixes a 34-rule global rejection precedence verbatim, so even the precedence-pair instances are uniquely derivable). The 24 `excluded_because:` stubs were not translated; all 24 `difficulty_instance` cross-references resolve to a real instance under the rule_id they name.

Individual asserts dropped as not-PRD-pinned (instances kept): scaffold-document claims ("§1.5 declares no PUT/PATCH/DELETE"), a coverage row's FK field name, exact minted DOI/persistent-identifier sequence values, `approved_cents == null` on rejection, `revision_round` unchanged by a decision, `embargo_until is None` under a GOLD_OA mandate, exact APCFund row counts (no list endpoint exists). Timestamp asserts compare the pinned instant plus three fractional digits rather than an exact zone rendering.

## Audit findings and fixes

- A central audit script (`/tmp/audit_2422.py`) checks C1–C4 mechanically: exactly one trailing `Design:` line per test resolving to a real non-stub instance, and every `PRD §x.y: "…"` citation matching PRD.md by whitespace-normalised literal match. Result: 0 tag errors, 0 coverage gaps, 0 stub translations, 0 non-verbatim citations.
- **One real defect caught and corrected mid-flight**: `test_13_request_validation_rules.py` initially carried paraphrased citations inventing non-existent error IDs (`ERR_AUTHOR_APPOINTMENT_WINDOW`, `ERR_GRANT_WINDOW_VIOLATION`) and a wrong precedence numbering; the real PRD rules are 22 `ERR_APPOINTMENT_WINDOW_EXPIRED` and 18 `ERR_GRANT_NOT_ACTIVE`. Now verbatim.
- The 11 residual audit warnings are parser artifacts, each reviewed by hand: PRD sentences containing nested double quotes (the four `author_guidance` strings, the `response_type` sentence) and §4 table rows cited as supporting context in `test_16` — every one of those tests also cites the rule-bearing §2.1/§2.9/§3.x prose.
- Static cross-check: every `api.<method>` resolves on `ApiClient`, every keyword argument binds against the real `test_helpers` signature, every `ApiErrorId.*` exists. No `skip`/`xfail`/placeholder anywhere; no test file mentions "scaffold"; nothing under `workspace/implementation/` was read or written; `test_helpers/` and `conftest.py` were not modified by the generators.

## Step 6: Generate implementation — 2026-09-02T18:17:33.259Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/`

Launcher / infra
- `start.sh` (executable) — `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `python3 -c "import flask"` fallback to `pip install -q -r requirements.txt`, then `exec python3 app.py`
- `requirements.txt` — `flask>=2.0`
- `app.py` — `create_app()` calls `clock.reset()` + `db.reset()` on every boot, registers 6 blueprints, installs `ApiError` / `HTTPException` / bare-`Exception` handlers; `app.run(host=0.0.0.0, port=$PORT or 10000, threaded=True, use_reloader=False)`

Core modules
- `clock.py` — logical clock pinned to `2026-08-01T00:00:00Z` at boot, never wall-clock; ISO-8601 UTC with exactly 3 fractional digits
- `db.py` — in-memory `Store` with 14 dicts plus insert/publication/ingest sequences; `new_row`, `set_fields` (version bumps only on real change unless `_force`), `sort_rows` (created_at, insert seq)
- `errors.py` (all 47 error IDs), `response.py` (meta/envelope, pagination `has_more`), `schemas.py` (exact field tuples for all 14 entities), `constants.py` (enums, regexes, screening weights, verbatim author-guidance strings, thresholds), `util.py` (Decimal `ROUND_HALF_UP`, `add_months` with day clamping, fiscal-year windows), `auth.py` (rule 1 → rule 2 ordering, ownership), `validation.py` (typed extractors, pagination, FK resolution)

Services — `services/{screening, compliance, determination, funding, invoicing, analytics}.py`
Routes — `routes/{helpers, reference, articles, fund_requests, invoices, deposits, ops}.py`

## Endpoint count

**55 non-static URL rules**, exactly matching the 55 declared endpoints.

## Storage

In-memory Python dicts only. A grep for `open(`, `sqlite3`, `json.dump`, `pickle`, `/tmp` across the implementation returns nothing. No seeding, preloading, or hardcoded entity data — a fresh boot returns `total_count: 0` for every collection.

## Boot verification (real process over HTTP)

Launched `PORT=48395 bash ./start.sh` in the background, then:
- `GET /articles` → 200, `{"meta":{...,"limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}` with `api_request_timestamp` = `2026-08-01T00:00:00.000Z` (clock correctly pinned, store empty)
- `POST /publishers` → 201 with full serialized row (`version: 1`, `screening_status: UNSCREENED`, `active_agreement_count: 0`)
- no auth headers → 401 `ERR_UNAUTHENTICATED`; unknown route → 404 `ERR_NOT_FOUND`
- process killed cleanly; server log shows no tracebacks

## Behavioural smoke tests (both pass)

Two end-to-end suites run in-process (`/tmp/smoke_2422.py`, `/tmp/smoke2_2422.py`, kept outside the implementation dir), ~120 assertions covering the happy path and error paths. Hand-verified values: screening `0 CLEARED` and `100 BLOCKED` / `60 PREDATORY_FLAGGED` bands; PROVISIONAL `TA_CAPPED` 300000×0.8=240000 capped at 100000 → author_share 140000; quota token cycle `ACTIVE → EXHAUSTED` and the FINAL-basis quota gate counting only FINAL tokens; waterfall `30000 + 170000` across `priority_rank` order with per-fund cap; withdrawal releasing encumbrances (`RELEASED`, committed back to 0); DOI `10.5555/ACME.1` and handle `hdl:2027/ir.000001` with supersession of the earlier `INGESTED` deposit; invoice pinned rounding `MATCH` vs `AMOUNT_VARIANCE → DISPUTED`; segregation-of-duties 403 when payer = approver; sweep counts across all four phases in order; analytics `ta_savings_cents 64000`, `negotiation_leverage_ratio 0.7111`.

Two things worth flagging for the worklog, both resolutions of genuine spec ambiguity:
1. `quota_position` counts all tokens on the agreement regardless of basis (the scaffold says only "count of tokens already held on T", unqualified), while the quota *gate* is basis-filtered per `quota_ok`. Consequence: a FINAL-basis check can legitimately return `quota_position` above `article_quota` when provisional holds exist.
2. `quota_position` excludes the article's own prior token, so re-running a check for the same article does not advance its position.

## Step 7: Run tests and iterate — 2026-09-02T18:26:14.495Z

All 8 parallel rounds passed on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1

**Sweep result (verified from the JSON artifacts, not the log):** all 8 rounds of `results.{1..8}.json` in `workspace/implementation/` report `total=117, passed=117, failed=0, errors=0, skipped=0`, and an explicit per-test scan found zero test entries with `status != "passed"` in any round. Round durations were tightly clustered (202.2–202.3s), and no round showed connection-reset/`Terminated` symptoms, so there is no evidence of the setsid-reaping artifact or of load-induced flakiness.

**Tests deleted:** none. No test failed in any round, so no test entered the diagnostic protocol and no PRD-silence / unique-derivability adjudication was required.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

Notes for the caller:
- The 8 `results.*.json` files are left in place under `workspace/implementation/` as sweep evidence.
- Scope check on the artifact: 117 collected test ids across `test_suite/test_01_…` through `test_18_…`; the implementation is 55 routes across `routes/{reference,articles,fund_requests,invoices,deposits,ops}.py` with domain logic in `services/{screening,compliance,determination,funding,invoicing,analytics}.py`, storage in-memory only (`workspace/implementation/db.py`), and the logical clock pinned to `2026-08-01T00:00:00Z` at boot (`workspace/implementation/clock.py`) — consistent with PRD §2.4 and with the no-seeding / in-memory-only cardinal rule.

**Orchestrator independent verification (per prior-run lesson that a Step 7 subagent can claim a clean sweep without artifacts):** re-read all 8 `results.*.json` directly with `json.load` — 8 files present, each `total=117 passed=117 failed=0 errors=0 skipped=0`. Claim confirmed.

## Step 8: Finalize PRD — 2026-09-02T18:26:14.495Z — SKIPPED

Skip condition from the skill is satisfied exactly: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent spawned; no `PRD_FINALIZED.md` produced. Step 9 will consequently start from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T18:34:20.232Z

Done. `PRD_COMPLETED.md` written.

**Files**
- Source: `workspace/PRD.md` — 449 lines, 100,544 chars
- Output: `workspace/PRD_COMPLETED.md` — 449 lines, 104,675 chars (**+4,131 chars**)
- Structure verified: identical heading set, identical table-row count (105), no lines added or removed (22 lines revised in place), ends at the §5 error catalogue table.

**Counts:** 25 edits — 20 ambiguity-pins, 5 mismatch-revisions.

**Changes**
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and non-member enum filter values are also `ERR_INVALID_REQUEST` — `validation.py:157`, `validation.py:231`
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by insertion sequence — `db.py:96`
- §2.4 — insert — ambiguity — `to_iso8601` may move the clock in either direction; missing/unparseable is 400; response carries only `current_utc` — `routes/ops.py:91`
- §2.5 — insert — ambiguity — an absent body FK is a shape failure (400), not a 404; non-string identifiers are 404 — `validation.py:208`
- §2.6 — insert — ambiguity — a non-integer or negative expected-version is 400, not 412 — `routes/reference.py:206`, `routes/deposits.py:57`
- §2.8 — revise — **mismatch** — `Author.apc_committed_cents` sums `ENCUMBERED` lines only (not the ENCUMBRANCE_INCLUSIVE total) — `services/funding.py:60`
- §2.10 — revise — **mismatch** — `Publisher.version` bumps only when the recomputed `active_agreement_count` actually differs — `services/determination.py:61`
- §3.1 — insert — ambiguity — all six screening signals required; retraction rate non-negative, median a non-negative integer, transparency an integer 0–100 — `routes/reference.py:94`
- §3.2 — insert — ambiguity — a coverage window escaping the agreement window is `ERR_INVALID_REQUEST` — `routes/reference.py:283`
- §3.3 — insert — ambiguity — `email` is any non-empty string, no address syntax enforced — `routes/reference.py:333`
- §3.3 — insert — ambiguity — no ordering enforced on appointment, award or fund-period date pairs — `routes/reference.py:337`, `:449`, `:487`
- §3.4 — insert — ambiguity — new article's initial `publication_date`/`doi`/`eligibility_route`/amount/counter values — `routes/articles.py:89`
- §3.4 — revise — **mismatch** — `quota_position` excludes the article's own held token and is basis-blind — `services/determination.py:198`
- §3.4 — insert — ambiguity — earliest-created line wins if several coverage lines match — `services/determination.py:122`
- §3.4 — revise — **mismatch** — a re-run with an `APPROVED`/`PAID` fund request is not refused; only the funding dimension is frozen — `services/determination.py:276`
- §3.5 — insert — ambiguity — `FUNDING_REQUESTED` is written unconditionally; multiple requests per article allowed — `routes/fund_requests.py:89`
- §3.5 — insert — ambiguity — withdrawal from `APPROVED` zeroes `approved_cents`/`fully_funded` but keeps `author_share_cents` — `routes/fund_requests.py:219`
- §3.5 — insert — ambiguity — withdrawal `reason` is required but never persisted — `routes/fund_requests.py:211`
- §3.6 — insert — ambiguity — publication leaves `compliance_status`/`deposit_deadline_on` and grant counters untouched — `routes/articles.py:170`
- §3.7 — insert — ambiguity — all six pricing fields including `validation_outcome` populated at creation — `routes/invoices.py:78`
- §3.7 — insert — ambiguity — payment cascade takes the earliest-created `APPROVED` request — `services/funding.py:226`
- §3.8 — revise — **mismatch** — at publication the mandate rule applies only its `embargo_until` half — `routes/articles.py:170`
- §3.8 — insert — ambiguity — an article with no grant is treated as licence requirement `ANY` — `routes/deposits.py:41`
- §3.8 — insert — ambiguity — `curation_note` is recorded on an `INGEST` decision too — `routes/deposits.py:172`
- §3.9 — insert — ambiguity — `fiscal_year` required, non-integer is 400, no range check — `routes/ops.py:79`

**Orchestrator verification:** `PRD_COMPLETED.md` is 449 lines / 104,675 chars, last heading `## 5. Error Code Catalogue`, final line the `ERR_AUTHOR_CAP_EXHAUSTED | 422` table row — ends at a real section boundary, not truncated.

**Pipeline complete.** All 9 steps done (Step 8 legitimately skipped per its documented skip condition).
