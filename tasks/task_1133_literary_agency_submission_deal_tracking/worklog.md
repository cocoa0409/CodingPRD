# Worklog — task_1133_literary_agency_submission_deal_tracking

## Step 1: Create task directory — 2026-08-10T22:42:22.808Z

Task directory `tasks/task_1133_literary_agency_submission_deal_tracking/` and its `workspace/` subdirectory pre-assigned by the caller and verified to exist; Step 1 auto-index scan skipped per caller instruction.

## Step 2: Generate scaffold — 2026-08-10T23:36:23.472Z

All three scaffold artifacts are generated, lint-clean, and audited. 

## Report

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys). Top-level keys verified: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 9 rules × 2 instances = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 63 instances (54 active + 9 `excluded_because` stubs citing §1.8 instances) across all nine claim-extraction-guide sections.

**Design summary:**
- Complexity profile: multi-party negotiation (primary) + ledger reconciliation (secondary); layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; flat topology; branching state-machine shape; approval-chain roles with segregation of duties; immediate consistency.
- 13 entities, 74 endpoints, 33 error codes, 6 calculations (3 dual-variant: commission_split provisional/final, auction_ranking frontlist/backlist, royalty_reconciliation NET/RETAIL), 10 state machines including 3 cyclic (Manuscript revision loop capped at 2, RoyaltyStatement audit re-open loop, Offer negotiate/revise loop), 2 OCC concurrency rules (Deal execute, SubmissionRound open).
- Flat URL space (`api_prefix: ""`, collections at `/query-letters`, `/deals`, etc.) was chosen deliberately: the lint's check (f) segment derivation requires two-segment single-GET paths, which nested URLs cannot satisfy.

**Key design decisions:**
- Editor exclusivity window `[p, p+2)` half-open (adjacency allowed) vs books-closed prefix `(-inf, N]` (boundary touch rejected) gives Rule 8 two genuinely different interval semantics on different resources.
- Lapse cascade (close-period → Agency period → QueryLetter LAPSED → Manuscript DECLINED, depth 3) and award cascade (offer accept → losing Offer SUPERSEDED → its Submission PASSED, depth 2) give Rule 4 two different triggers with per-hop causation spelled out in side_effects.
- All assert literals were executed against the formulas in Python — every one matches (gross 1136000 NET vs 1120500 RETAIL; waterfall 50000/25000/25001 from advance 100001; auction rank flip 120000/210000 vs 1612000/206000; tier boundary 500000 vs 500125; commissions 37500 vs 25000; earn-out clamp 500000 and delta-adjusted 967300; triage 90/40/60).

**Audit results:**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (74 endpoints, 13 entities, 18 + 54 instances, 1253 calls scanned, exit 0).
- All `grounds` references resolve to declared §1.1–§1.7 elements; instance names unique across both files; zero unbound `${var}` placeholders; every error code is exercised by at least one instance; no forbidden concurrency vocabulary; roles in all calls ⊆ RBAC matrix; offer-create ordering (SENT/UNDER_CONSIDERATION precondition) and OCC version freshness verified mechanically across every chain.
- One structural note documented in the corner file: `ERR_ROUND_HAS_LIVE_OFFERS` can only fire standalone if an implementation checks offers before submissions within the shared priority-19 band, since a live offer always implies an OFFER_EXTENDED submission — both error ids are conformant there.

## Step 3: Copy shared files — 2026-08-10T23:36:46.606Z

Copied `./INSTRUCTION.md` to `tasks/task_1133_literary_agency_submission_deal_tracking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T23:46:51.209Z

Done. The PRD is generated and all three hard contracts pass.

## What was produced

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/PRD.md` (342 lines)

**Structure:**
- **§1 Introduction** — 2 paragraphs framing the agency pipeline (slush → evaluation → signing → submissions → offers/auctions → deals → royalties/audit) and the four segregated operator roles.
- **§2 Global Specifications** (11 subsections) — RBAC with `X-User-ID`/`X-User-Role` and per-role identity translation (`Agent` is entity-backed; the other three are opaque); the §2.2 envelope pasted **byte-identical** from `section-2.2-response-structure.md` (verified programmatically); pagination (limit default 10, min 1, max 100; offset 0; `created_at` ascending; four meta fields); then domain-derived subsections: multi-tenancy/agency scoping, common resource properties, the royalty period clock, slush capacity/posture, integer-cents and pinned floor ordering, the full 19-priority validation pipeline in explicit prose order, OCC (only round-open and deal-execute take version fields), and cascade conventions.
- **§3 Business Logic** (8 subsections) — bootstrapping/roster; query intake & triage score; manuscript evaluation & revision loop (cap 2, accept threshold 70); client agreements; submission rounds & editor tracking (capacity, duplicate, half-open exclusivity window `[p, p+2)`); offers & auction ranking (frontlist/backlist variants with the scaffold's worked A/B example); deal execution & advance waterfall (50%/25%/remainder, 100,001 → 50,000/25,000/25,001); royalty reconciliation & audit (tier thresholds 5,000/7,500, escalators 0.025/0.0125, NET-vs-RETAIL worked example 1,136,000 vs 1,120,500, provisional/final commission example 37,500 vs 25,000, tolerance 500, earn-out cap and clamp).
- **§4 Endpoint table** — all 48 endpoints, 4 columns only. [Orchestrator note: actual table row count verified = 74, matching SCAFFOLD.yaml's 74 endpoints; "48" in the subagent's summary prose was a typo.]
- **§5 Error catalogue** — all 33 error IDs, 2 columns only, no trigger conditions.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body: 5 required, 5 present, 0 missing (title, eval_score, agent_id, expected_submission_round_version, expected_deal_version beyond entity fields)
- endpoints[].query_params: 18 required, 18 present, 0 missing
- endpoints[].path_params: 13 required, 13 present (all in §4 table paths)
Status: PASS

Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in ordered prose (§2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_*_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed (from/to, preconditions with error IDs, side effects incl. cascade links), 0 missing
- calculations[]: 6 checked, 6 fully expressed (constants, variants, pinned rounding order, worked examples), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, 48 expressed, 0 missing
- entities[].fields[] structured content: 72 checked, 72 reconstructible (defaults, nullability, integer-cents typing), 0 missing
- sibling-branch symmetry: 11 groups checked (RECEIVED/UNDER_NEGOTIATION offer exits, SCHEDULED/DUE/LATE payments, etc.), 11 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 502
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: §2.2 verbatim block byte-identical (including `req_RANDOMALPHANUM123456` and empty `"data": { }`); all 33 error IDs appear in §2/§3 prose; all 62 enum/state values present as exact UPPERCASE strings; no fuzzy wording ("approximately", "roughly", etc.) or pseudocode operators (`>=`, `==`, `+=`) in prose. The forbidden difficulty/corner design files were not opened.

## Step 5: Generate unit tests — 2026-08-11T00:22:06.699918641Z

Generation complete. Summary of what was produced and the key decisions:

## Deliverables

**`test_helpers/` (Stage 1)** — 9 files under `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/test_helpers/`:
- `types.py` — 14 status enums + 13 entity TypedDicts (all entities carry `common_fields: true`, so all include id/created_at/updated_at/version; nullable computed fields typed `Optional`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (creates, gets, filtered lists, and all state-transition actions).
- `api_errors.py` — `ApiErrorId` enum + all 33 error→HTTP mappings registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` (UUID/timestamps/version/enum/type checks, nullable-aware) + `assert_deal_invariants` (earn-out ≤ advance).
- `factories.py`, `constants.py` (triage weights, tier thresholds, escalators, waterfall fractions, audit tolerance, exclusivity window), `test_users.py` (opaque role constants + `make_agent_headers(user_id)` builder for the entity-backed Agent role).
- `fixtures.py` — composable pipeline builders: roster → accepted manuscript → signed agreement → round/submission/offer → negotiating/executed/active deal → statements, using `get_success_data` throughout and threading agent identity via `make_agent_headers(agent["id"])`.

**`test_suite/` (Stage 2)** — `conftest.py` + 10 numbered test files, **90 tests**: all 18 difficulty instances × 2 tests, all 54 non-stub corner instances × 1 test. The 9 `excluded_because` stubs were not translated; all their `difficulty_instance` cross-references verified to resolve.

## Verification performed
- `py_compile` + pyflakes clean (no undefined names; unused imports removed).
- `pytest --collect-only` succeeds: 90 tests.
- Programmatic audit: every test docstring ends with exactly one `Design:` line resolving to a real instance; every difficulty instance has ≥2 tags; every non-stub corner instance has ≥1; every docstring's PRD citation contains a ≥8-word substring that literally greps in `workspace/PRD.md` (0 failures). No `skip`/`skipif`/`xfail` markers anywhere.

## Judgment calls (PRD-first adjudication)
- **Absolute version numbers** (e.g. `version == 1` after create, `== 2` after open) are not uniquely derivable from the PRD ("starts at its initial value…increments by one"), so those corner instances (`agency_create_applies_defaults`, `agent_version_increments_on_toggle`, both OCC tests) assert the derivable increments/relative form (`v2 == v1 + 1`, `vAfter == stale + 1`) instead of literals — the "relax" option from the final citation pass rather than skipping, since each instance's core claim is PRD-covered.
- **`close_round_with_live_offer_rejected`**: a standalone `ERR_ROUND_HAS_LIVE_OFFERS` is not uniquely derivable (a live offer implies an OFFER_EXTENDED submission, tripping the equal-priority live-submissions gate), so the test translates the instance's own literal asserts — decline cascades the submission to PASSED, close then succeeds.
- **`request-manuscript` status code** is PRD-ambiguous (creates a Manuscript = 201 vs modifies the letter = 200), so that path uses the lenient `get_success_data` and asserts content, not code.

## Step 6: Generate implementation — 2026-08-11T00:22:06.699918641Z

Done. Complete Python + Flask implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/implementation/`.

**Files**
- `start.sh` — executable; guarded dependency install (`if ! python3 -c "import flask"` no-op when present), then `exec python3 app.py` in foreground
- `requirements.txt` — flask only
- `app.py` — app factory, global request lock, envelope-shaped 404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `core.py` — in-memory store (empty at boot, no seeding), error catalog constants, envelope (`meta.api_request_id` `req_…` / `api_request_timestamp` 3-fraction-digit ISO UTC, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 4 roles), strict body validator (required fields, enums, ranges, no undeclared fields), pagination (`limit` default 10 clamped [1,100], `offset`, `total_count`, `has_more`), Agent-tenancy scoping
- `domain.py` — all six calculations (`slush_triage_score`, `auction_ranking` frontlist/backlist, tiered `royalty_reconciliation` with pinned floor order, `commission_split` provisional/final, `advance_waterfall` remainder bucket, `advance_earnout` clamps) plus derived-field recompute helpers
- `routes_roster.py`, `routes_queries.py`, `routes_agreements.py`, `routes_offers.py`, `routes_royalties.py` — all 47 endpoints from the endpoint table

**Key behaviors implemented per PRD/scaffold**
- Validation pipeline order: auth(400) → role(403) → body(400) → existence/tenancy(404) → OCC(412) → state(409) → SoD → assigned-agent → active counterparties → business gates
- OCC on `submission-rounds/open` and `deals/execute` with 412 before state checks
- Full cascade chains: award cascade (Deal creation → supersede losers → their submissions pass; fan-out withdraws), lapse cascade (close-period lapses REQUESTED queries with `requested_period_index <= period_index-2` → manuscript DECLINED), termination cascades (SCHEDULED/DUE → WAIVED; LATE/PAID untouched), deal activation on first PAID installment + close-period backstop
- Editor exclusivity half-open window `[p, p+2)`; segregation of duties on offer accept / deal execute; auction ranking with `Decimal` math (verified the scaffold's frontlist/backlist A/B example ranks B first under FRONTLIST, A first under BACKLIST)
- Royalty math verified against the PRD example shape (tiered floors per line, escalators 0.025/0.0125); advance waterfall 100001 → 50000/25000/25001
- Every mutation (including cascades and derived-field changes) bumps `version` and refreshes `updated_at`; versions start at 1

**Verification**: two smoke suites (~90 assertions) run against fresh boots via `start.sh` — both report zero failures, covering the full pipeline (intake → evaluation → agreement → rounds → offers/auction → deal → installments → statements/audit), error IDs/statuses, tenancy isolation, OCC, and the period/book-close sweeps. `bash start.sh` boots in ~2s and binds `0.0.0.0:$PORT`.

[Orchestrator note: route-table cross-check performed before Step 7 — SCAFFOLD.yaml declares 74 (method, path) endpoint pairs; implementation registers exactly the same 74 pairs (0 missing, 0 extra). The "48"/"47" figures in the Step 4/6 summaries were prose typos; actual counts match.]

## Step 7: Run tests and iterate — 2026-08-11T00:51:39.000Z

[Orchestrator note: resumed run. The earlier headless attempt was SIGTERMed at Step 7 with zero results files on disk; 8 orphaned `python3 app.py` servers from that attempt were killed by verified PID (cwd-checked; other tasks' live processes untouched). Baseline 8-round sweep then run by orchestrator via `workspace/sweep.sh`: all 8 rounds completed, identical 87/90 — 3 deterministic failures (`test_statement_touching_closed_prefix_rejected`, `test_statement_adjacent_above_closed_prefix_allowed`, `test_future_statement_rejected_at_intake`), all tripping `ERR_INVALID_REQUEST: undeclared field(s): receipts, units` at royalty-statement intake before the targeted business gate. One synchronous fix subagent then owned the diagnose→fix→rerun loop. Its verbatim summary follows.]

All 8 rounds pass 90/90. Route parity preserved by construction — I made zero edits to `implementation/` (the count reflects exactly what the orchestrator verified pre-sweep; no route surface was touched).

Summary:

- **Iterations run:** 2 sweeps (1 baseline by orchestrator: 87/3 deterministic across 8 rounds; my iteration 1 sweep: 3 original failures fixed but a transient infra flake; my iteration 2 sweep: clean 90/90 × 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to test_helpers/:** one fix in `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/test_helpers/factories.py`, factory `create_royalty_statement_payload` — it now pops the `units`/`receipts` tuple shorthands from overrides and unpacks them onto the PRD-declared per-format fields (`units_hardcover`/`units_trade`/`units_ebook`, `net_receipts_hardcover_cents`/`net_receipts_trade_cents`/`net_receipts_ebook_cents`) before merging remaining overrides. Why: three tests passed tuple kwargs straight into the factory, whose blind `defaults.update(overrides)` injected undeclared `units`/`receipts` keys into the intake payload; PRD §3.8 declares only the per-format fields and PRD §2.4 rule 3 mandates "no undeclared fields (`ERR_INVALID_REQUEST`, 400)", so the PRD-faithful strict validator correctly rejected the request before the targeted business gates (`ERR_BOOKS_CLOSED`, `ERR_FUTURE_STATEMENT`, 201) could fire. The fix mirrors the established tuple-unpacking convention already used by `fixtures.create_statement` (fixtures.py:347-363) and makes emitted payloads PRD-conformant. All four call sites verified compatible (tuple path and per-format path both unit-checked).

- **Fixes applied to test_suite/:** none — the three failing tests' assertions trace verbatim to PRD §3.8 ("a `period_index` beyond the agency's current `period_index` ... fails with `ERR_FUTURE_STATEMENT`, while a `period_index` at or before `books_closed_through_period_index` ... fails with `ERR_BOOKS_CLOSED`") and §2.6 ("statements may only be intaken for a period strictly after `books_closed_through_period_index` and no later than the current `period_index`"); STEP 1 coverage and unique-derivability both passed, and the defect was in the helper-layer payload construction, so the test functions needed no change.

- **Fixes applied to implementation/:** none — the strict body validator in `workspace/implementation/routes_royalties.py` is PRD-required and was behaving correctly; no checks were weakened or removed.

- **Flakiness note:** iteration 1's sweep showed a setup-phase error (`test_query_initial_state_received`, 6 of 8 rounds) — the runner's per-test server restart exhausted its 15-second health-poll window; all failures fired at the same wall-clock second (~13s into the sweep, during the 8-way process-spawn import storm), on a test my change cannot influence, and the server cold-boots in ~250ms when uncontended. Diagnosed as transient host contention from concurrent pipelines, not an artifact defect; iteration 2's sweep confirmed: 90/90 passed in all 8 rounds.

## Step 8: Finalize PRD — 2026-08-11T00:53:30.000Z

Step 8 was NOT skipped: Step 7 recorded 1 `test_helpers/` fix, so the zero-fix skip condition was not met. Finalizer subagent ran synchronously; verbatim summary follows.

All verification is complete. The single Step 7 item was a pure test_helpers fixture bug — PRD and implementation already agreed — so no PRD edits are warranted. PRD_FINALIZED.md exists as a byte-identical copy.

## Summary

**Line counts / %-delta:** PRD.md = 342 lines; PRD_FINALIZED.md = 342 lines; delta = 0 lines (0.0%). Byte-identical copy (verified via `diff`).

**Changes:** none. 0 edits.

**No-edit justification (verification search performed in lieu of per-edit logs, since the step_7_diff contains exactly one item and it is a pure fixture bug):**

- **Step 7 item:** `test_helpers/factories.py:create_royalty_statement_payload` (lines 145–172) now pops `units`/`receipts` tuple shorthands from overrides and unpacks them onto the per-format fields before merging. No implementation change; no test_suite change.
- **Subject checked:** the royalty-statement intake field schema and the undeclared-field ban.
- **Impl paths enumerated and read:**
  - `workspace/implementation/routes_royalties.py` lines 20–33 — `create_statement` declares exactly nine intake fields: `deal_id`, `period_index`, `units_hardcover`, `units_trade`, `units_ebook`, `net_receipts_hardcover_cents`, `net_receipts_trade_cents`, `net_receipts_ebook_cents`, `publisher_reported_royalty_cents`.
  - `workspace/implementation/core.py` lines 222–234 — `parse_body` computes `extra = set(raw.keys()) - allowed` and rejects any undeclared key with 400.
- **PRD pins confirmed:**
  - PRD §3.8 (PRD.md line 213) declares exactly those per-format fields for statement intake — verbatim: "per-format unit counts `units_hardcover`, `units_trade`, and `units_ebook` (each zero or greater), the per-format receipts `net_receipts_hardcover_cents`, `net_receipts_trade_cents`, and `net_receipts_ebook_cents`, and the `publisher_reported_royalty_cents`".
  - PRD §2.9 rule 3 (PRD.md line 111) mandates "no undeclared fields (`ERR_INVALID_REQUEST`, 400). Applies to every endpoint with a body." (The step_7_diff's "§2.4 rule 3" citation is a mislabel; the operative rule is §2.9 rule 3 — substance identical.)
- **Conclusion:** implementation behavior is uniquely determined by the existing PRD prose at both sites; the fixture was the only non-conformant artifact. A fresh implementer reading PRD.md alone would build the same strict validator and the same nine-field intake schema. Any added wording would be redundant at best and risks violating the no-new-mismatch rule, so PRD_FINALIZED.md is shipped unchanged per method step 0 / the zero-edit provision.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/PRD_FINALIZED.md`

[Orchestrator verification: PRD_FINALIZED.md present (53,667 bytes), `cmp` confirms byte-identical to PRD.md, 342 lines.]

## Step 9: Complete PRD — 2026-08-11T01:07:30.000Z

Completeness-scan subagent ran synchronously over PRD_FINALIZED.md vs implementation/. Verbatim summary follows.

## Summary

**File stats**
- Source `PRD_FINALIZED.md`: 342 lines / 53,667 chars → `PRD_COMPLETED.md`: 345 lines / 57,670 chars. Char delta: **+4,003**. 18 edit sites, all in-paragraph inserts/revisions (plus one table row); no new sections.

**Counts**: 20 ambiguity-pins, 2 mismatch-revisions.

**Changes** (one bullet each):

- §2.1 — insert — ambiguity — unknown `Agent`-role `X-User-ID` is not an auth failure: scoped reads/writes 404, lists return empty — `core.py:166-179`, `core.py:300-307`
- §2.2 — insert — ambiguity — undefined paths/unsupported methods → `ERR_NOT_FOUND` 404 in envelope; unexpected failures → `ERR_INTERNAL` 500 in envelope — `app.py:38-53`
- §2.3 — revise — ambiguity — `limit`/`offset` are clamped (not rejected), non-integer values 400, sort ties break by insertion order, `total_count` is the filtered pre-pagination count, `has_more` semantics — `core.py:276-297`, `core.py:320`
- §2.4 — insert — ambiguity — list endpoints scope `Agent` callers to their own agency; other roles see all agencies — `core.py:300-307`
- §2.5 — revise — ambiguity — `version` starts at 1 (was "starts at its initial value") — `core.py:48-51`
- §2.9 item 3 — revise — ambiguity — body must be a JSON object, strict types (bool/int/non-empty string), null rejected unless nullable, added ranges (fractions ≥ 0, `max_editors` ≥ 1, `period_index`/expected-version ≥ 0), fieldless endpoints reject any body field — `core.py:222-272`
- §3.1 — revise — ambiguity — `commission_pct` number ≥ 0, `slush_capacity` integer ≥ 0 at agency creation — `routes_roster.py:23-27`
- §3.1 — revise — ambiguity — duplicate email within agency rejected as `ERR_INVALID_REQUEST` (agents, authors, editors) — `routes_roster.py:115-116,176-177,213-214`
- §3.1 — insert — ambiguity — deactivation does not revoke the record's own calling privileges; only blocks new references — `routes_roster.py:141-162`, `routes_queries.py:72-73`
- §3.1 — revise — ambiguity — author status also moves `FORMER` → `CLIENT` on later acceptance/signature — `domain.py:55-59`
- §3.4 — revise — ambiguity — `commission_pct_override` is the API's one nullable field; omitted or explicit null both leave it unset — `routes_agreements.py:28`
- §3.5 — revise — ambiguity — send gates evaluated in pinned order: submission state → round open (`ERR_ROUND_NOT_OPEN`) → editor active → exclusivity window — `routes_agreements.py:279-298`
- §3.6 — revise — ambiguity — offer revise requires `advance_cents` + three fractions; omitted `royalty_basis`/rights flags retain current values rather than resetting — `routes_offers.py:28-40,96-108`
- §3.6 — revise — ambiguity — auction ties break by earlier `created_at` then insertion order; non-live offers carry `auction_rank` null and leaving the live set clears it — `domain.py:106-121`
- §3.6 — revise — ambiguity — deal `client_agreement_id` is null in the degenerate no-`SIGNED`-agreement case — `routes_offers.py:164-170`
- §3.7 — revise — ambiguity — every accepted amendment call increments `version`, even a fieldless no-change one — `routes_offers.py:234-238`
- §3.7 — revise — **mismatch** — installment aging is one step per close: `SCHEDULED`→`DUE` when new period ≥ due (even on overshoot, e.g. `ON_SIGNING`), `DUE`→`LATE` only when strictly past due; the old prose's "advances past due → LATE" reading contradicted the single-step sweep — `routes_roster.py:71-80`
- §3.8 — insert — ambiguity — statement intake imposes no deal-state gate (only the two period gates); only reconciliation requires a live deal — `routes_royalties.py:34-40,79-83`
- §3.8 — revise — ambiguity — at audit opening the tolerance check fires before the closed-books check when both would fail — `routes_royalties.py:113-118`
- §4 intro — insert — ambiguity — dual-effect action endpoints return `200`: request-manuscript carries the spawned `Manuscript`, offer acceptance the accepted offer, deal execution the executed deal — `routes_queries.py:114`, `routes_offers.py:203,278`
- §4 filters — revise — **mismatch** — every list endpoint filters by `agency_id` and `status` (original text listed them only for roster resources); filters match exactly, `period_index` compared as integer (non-integer → 400), unrecognized query params ignored — `core.py:308-319`, e.g. `routes_roster.py:138`
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row to the error catalogue — `app.py:48-53`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/PRD_COMPLETED.md`

[Orchestrator verification: PRD_COMPLETED.md present (345 lines, 57,670 bytes, +4,003 chars over PRD_FINALIZED.md).]
