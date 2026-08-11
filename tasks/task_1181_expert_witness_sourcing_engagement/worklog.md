# Worklog — task_1181_expert_witness_sourcing_engagement

## Step 1: Create task directory — 2026-08-11T12:24:02.000Z

Pre-assigned output folder `tasks/task_1181_expert_witness_sourcing_engagement` with `workspace/` subdirectory already exists (created by pipeline launcher). Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate scaffold — 2026-08-11T13:20:00.000Z

Scaffold generation complete and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/SCAFFOLD.yaml` — 949 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 924 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/SCAFFOLD_CORNER_DESIGN.yaml` — 962 lines (single top key `scaffold_corner_design`)

## Counts

- Entities: 12 (Expert, Case, EngagementRequest, ConflictCheck, CredentialReview, Engagement, DocumentProduction, Report, TestimonySchedule, Venue, Invoice, Evaluation)
- Endpoints: 56; State machines: 10; Calculations: 8; Validations: 30 (ordered priorities); Errors: 29; Roles: 6 (Expert is `entity_backed:Expert`, rest opaque); OCC concurrency rules: 2 (`engagement-amend-stale-version`, `case-budget-revision-stale-version`, both 412 with `expected_*_version` placeholder-disciplined payloads)
- Difficulty instances: 21 total — dual_variant_calc 2, combinatorial_formula 3 (modes a, b, c all distinct), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2
- Corner instances: 42 total across all nine taxonomy sections — 34 full recipes, 8 `excluded_because` stubs (all citing real §1.8 instance names)
- Lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (697 calls scanned; 1 FK_REVERSE_UNREACHABLE found and fixed by adding `GET /litigation/engagements/{id}/evaluations`)

## Design highlights (harder-than-expert levers actually used)

- **Consequential dual variants**: the Expert rating's SIMPLE (3.00) vs DECAYED (2.33) variants disagree *and the probation cascade consumes only the DECAYED one* — picking the wrong variant flips observable state; Case committed (1,380,000) vs actuals (20,000) diverge on identical data.
- **All three combinatorial modes**: tiered multipliers + nested min(expense, cap) (a); pinned per-line-then-sum rounding where the counterfactual order (10,002 vs 10,001) is enforced via `ERR_INVOICE_AMOUNT_MISMATCH` (b); retainer drawdown with explicitly pinned evaluation order to break the allowed-amount ↔ remaining-balance circularity (c).
- **Depth-3/4 transitive cascades from distinct triggers**: evaluation → rating recompute → auto-PROBATION → PENDING checks auto-FLAGGED → request reverts SCREENING→OPEN; terminate → DISCLOSED report WITHDRAWN → Case TRIAL_PREP→DISCOVERY revert, plus parallel schedule/doc/invoice/retainer-refund links.
- **Two interval semantics on two resources**: Expert calendar half-open `[start, end)` (12:00 adjacency legal, 11:59:59 conflicts) vs Venue closed intervals + 30-min turnover buffer (13:00 conflicts on the touching buffered edge, 13:00:01 clears).
- **Boundary-exact probes**: budget `==` remaining approves, +1 cent rejects; Daubert exclusions `>= 3` bars (2 passes, 3 fails); report submit at exactly `deadline_at` passes, +1s fails; retainer overfund by 1 cent rejects while exact funding activates.
- **Validation-priority conflicts on different category pairs**: (state vs business_fiscal) on invoice approve; (business_safety vs business_constraint) on engagement create.
- **Segregation of duties** role model: creator-vs-approver `X-User-ID` comparison, ConflictAnalyst cannot WAIVE, Expert ownership checks on sign/submit/resubmit.
- **OCC on two create-with-supersede writes** (engagement amend, case budget revision), tested happy-then-stale with `${var}`-captured versions.

## Step 3: Copy shared files — 2026-08-11T13:22:54.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1181_expert_witness_sourcing_engagement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T13:47:31.000Z

PRD generation complete. All three hard contracts pass.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/workspace/PRD.md` — 52,181 bytes, 340 lines.

**Section overview**
- §1 Introduction — 2 paragraphs: business context (expert-witness lifecycle for a litigation support firm) + system goals (segregation of duties, retainer ledger, pinned rounding, logical clock, `/litigation` mount).
- §2 Global Specifications — 11 subsections: 2.1 RBAC (6 roles, per-role identity semantics incl. `entity_backed:Expert` vs opaque), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties (incl. Evaluation's `common_fields: false` exception — no `updated_at`/`version`), 2.5 Logical Clock (startup default `2026-05-01T00:00:00Z`), 2.6 OCC (both `concurrency_rules` with endpoint, `expected_engagement_version`/`expected_case_version`, `ERR_STALE_VERSION`/412), 2.7 Monetary Precision, 2.8 Retainer Ledger (conservation invariant + pinned 5-step drawdown order), 2.9 Dual-variant fiscal posture (`actuals_paid_cents` vs `committed_cents` + schedule-estimate formula), 2.10 Calendar/venue booking geometry (half-open expert vs closed+buffered venue intervals), 2.11 Validation ladder + left-to-right 404 resolution.
- §3 Business Logic — 8 subsections organized by lifecycle: roster/ratings/probation cascade, matter opening + dual-track screening, engagement negotiation/funding/amendment, document production privilege tiers, report review protocol, testimony scheduling, invoicing/budget/settlement, termination cascades/close-out/evaluations. All 8 calculations rendered as precise prose (incl. the pinned per-line-rounding worked example 10002 vs 10001); all 29 error IDs surface near their triggers; explicit priority orderings stated for every multi-rule endpoint (engagement creation 6→7→8→9→12→13→14, schedule create/confirm 17→18→19→20→23, invoice create/resubmit 17→24, approve 11→26).
- §4 Endpoint table — 56 rows, 4 columns (Method, Path, Description, Authorized Role(s)); verified to match scaffold endpoints exactly.
- §5 Error catalogue — 29 rows, 2 columns; statuses verified against scaffold.

**Hard contract results**
- Contract 1 (field-name coverage): **PASS** — entities[].fields 71/71 present, 0 missing; endpoints request_body 60/60, 0 missing; query/path params 1/1 (`id`), 0 missing (87 unique identifiers total).
- Contract 2 (rule coverage / zero-silence): **PASS** — 29/29 validations expressed with their `error_id` (priority orderings stated in prose where rules share an endpoint); 2/2 OCC rules with write-endpoint + OCC field + `ERR_STALE_VERSION`/412 and no race-framing; all 62 state-machine transitions fully expressed (from/to states, preconditions, side effects, cascades); 8/8 calculations rendered step-for-step with constants and boundary inclusivity (Daubert ==3 bars/==2 passes, budget equality passes, capacity ==cap fails, deadline equality passes, 72h boundary fee 0); sibling branches rendered symmetrically (case close ×3 postures, removal ×2, settle/review/resolve outcomes, terminate ×2 postures).
- Contract 3 (§3 path purity): **PASS** — 505 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos.

**Design decisions:** §2 uses 11 domain-derived subsections (retainer ledger, dual-variant fiscal posture, booking geometry, logical clock as first-class concerns); §3 groups by lifecycle stage (8 subsections) rather than the example's 7-step pattern; monetary rounding stated as "round half-up to the nearest whole cent" for money (per the scaffold's worked example, which only holds at cent resolution) and "two decimal places" for ratings; the withheld DIFFICULTY/CORNER files were never opened; PRD ends at §5 with no audit footer.

## Step 5: Generate unit tests — 2026-08-11T14:30:00.000Z

All verification steps pass. Final summary:

## Test generation complete — task_1181_expert_witness_sourcing_engagement

### Files written

**`test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/test_helpers/`):
- `types.py` — 13 status enums, role enum, 12 entity TypedDicts (`Evaluation` correctly omits `updated_at`/`version` per the immutable-record exception)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 42 endpoint methods including `set_clock`
- `api_errors.py` — 29 `ApiErrorId` values + HTTP status map, registered with the framework
- `assertions.py` — per-entity assertions + `assert_retainer_invariant`
- `factories.py`, `constants.py` (Daubert bar 3, probation 3.0/2 evals, 180-day decay, 72h cancel window, 30-min venue buffer, kind multipliers), `test_users.py` (opaque-role shared constants + per-instance builders incl. entity-backed `make_expert_headers`)
- `fixtures.py` — composite scenario pipeline (expert→case→request→screening→engagement walked to DRAFT/PROPOSED/SIGNED/ACTIVE/CLOSED), report/document/schedule/invoice/evaluation lifecycle helpers
- `__init__.py` — barrel export

**`test_suite/`** (under `.../test_suite/`): `conftest.py` + 10 domain-organized files (`test_01_experts_roster` … `test_10_cascades_and_evaluations`).

### Coverage vs design indices
- **Queue A (difficulty): 21/21 instances covered, 2 tests each = 42 tests** (all 21 passed the PRD-first filter; every rule — dual-variant budget/ratings, per-line rounding, drawdown order, revision/dispute cycles, both transitive cascades, both priority pairs, all three boundary checks, all three cross-entity gates, both overlap regimes, both compensating invariants — is verbatim-covered and uniquely derived in PRD §2.5–§3.8)
- **Queue B (corner): 33/34 non-stub instances covered (1 test each)**; 8 `excluded_because` stubs verified to resolve to real queue-A instances and not translated
- **Skipped (1):** `Corner/entities/engagement_request_requires_existing_case` — PRD §2.11 pins `ERR_NOT_FOUND` only for *path* identifiers; a dangling `case_id` in the request body has no uniquely-derivable outcome (400/404/422 all PRD-consistent)
- One assertion relaxed, not skipped: `expert_creation_applies_defaults` drops `version == 1` (PRD never pins the initial version value)

### Verification results
- **py_compile:** all 19 files OK
- **pytest --collect-only: 75 tests collected, 0 errors**
- **Tag audit:** 75/75 tests carry exactly one terminal `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance; the only shortfall is the intentional skip above (gap stays a gap — no placeholder, no skip marker)
- **Citation audit:** 117 verbatim PRD quotes across all docstrings, every ≥8-word span survives literal whitespace-normalized grep of `PRD.md` — CLEAN
- **Hygiene:** zero `pytest.mark.skip`/`skipif`/`xfail`, zero "scaffold" references in generated code

## Step 6: Generate implementation — 2026-08-11T14:30:00.000Z

Second fresh boot: 118/118 pass again. Implementation complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/workspace/implementation/`):
- `start.sh` — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"` guard so per-test reboots skip pip), `exec python3 app.py`
- `requirements.txt` — `flask>=2.2,<4`
- `app.py` — Flask app factory, auth `before_request`, envelope error handlers (ApiError/404/405/500)
- `db.py` — in-memory stores (empty at boot, zero seeding), logical clock (default exactly `2026-05-01T00:00:00Z`, never wall-clock), monotonic 3-fractional-digit UTC timestamps, `base_record`/`touch` (uniform updated_at + version increment rule)
- `lib.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), auth (`X-User-ID`/`X-User-Role`, six roles), body validators, pagination (`limit` 1–100 default 10, `offset` default 0; `total_count`/`has_more` in meta)
- `services.py` — serializers (exact scaffold field sets; Evaluation omits `updated_at`/`version`), per-line-round-then-sum invoice math via `Decimal` ROUND_HALF_UP, retainer ledger, case dual-variant aggregates (actual/committed), expert ratings (simple + 0.5^floor(age_days/180) decayed), half-open expert vs closed+30min-buffer venue overlap, probation and termination cascades
- `routes_experts.py`, `routes_cases.py`, `routes_screening.py`, `routes_engagements.py`, `routes_productions.py`, `routes_reports.py`, `routes_schedules.py`, `routes_invoices.py`, `routes_evaluations.py`, `routes_clock.py`

**Route verification**: 56 declared in SCAFFOLD.yaml `endpoints[]` vs 56 registered in the Flask url_map — zero missing, zero extra (verified programmatically via `/tmp/verify_routes_1181.py`).

**Boot verification**: `bash -n start.sh` clean; `py_compile` clean on all modules; `PORT=18799 timeout 5 bash start.sh` boots and serves HTTP 201 within ~2s (exit 124 from the timeout as expected for a foreground server). Two consecutive fresh boots both passed the full smoke suite, confirming clean per-test reboots.

**Smoke coverage** (118 assertions, all passing, against fresh-booted servers):
- *Envelope/errors*: 401/400/403/404/409/412/422 shapes, error `meta` contains only request id+timestamp, `req_` prefix, 400-before-403 ordering, pagination meta fields + limit bounds
- *Main lifecycle*: expert → case (INTAKE→SOURCING auto) → request → screening (duplicate-screening 409, SCREENING→READY) → engagement (seven gates in pinned order incl. Daubert ≥3 bar, duplicate case+expert, capacity) → propose/counter/re-propose-with-rate/sign (nda, SOURCING→ENGAGED) → fund (overfund 422, exact-fund activates, zero-retainer activation) → termination → case close
- *Cascades*: ACTIVE termination withdraws DISCLOSED report (case reverts TRIAL_PREP→DISCOVERY), cancels schedules fee-free, recalls REQUESTED productions (ACKNOWLEDGED untouched), rejects SUBMITTED invoices; probation cascade flags PENDING checks with `ROSTER_PROBATION` and reverts SCREENING→OPEN
- *OCC*: stale `expected_engagement_version`/`expected_case_version` → 412 ERR_STALE_VERSION; matching versions succeed
- *Boundary rules*: report submit exactly at deadline passes / strictly after → 409; disclose ≥ trial_date → 409; expert-calendar adjacency allowed (half-open) while venue touching at exactly end+30min conflicts (closed+buffer); cancel at exactly start−72h → fee 0, inside window → fee = 0.5×est_hours×rate×1.25 with draw capped at retainer remaining; budget equality passes / exceed → 422; per-line-vs-sum rounding pinned (rate 10001, two 1h TRAVEL_TIME lines → 10002 accepted, 10001 rejected); segregation-of-duties 403 on creator-approver
- *Ledger/aggregates*: retainer invariant (funded = drawn + refunded + remaining) after fee draw and termination; committed_cents = actuals + approved + pending + ACTIVE retainer + CONFIRMED estimates verified numerically

One note for the environment: several short-lived `python3 app.py` processes from other tasks' concurrent pipeline runs are present on this host — I verified they're not from this workspace and left them untouched; my verification server was killed by its listening PID only.

## Pre-Step-7 route parity check (orchestrator) — 2026-08-11T14:29:57.000Z

Independently diffed the Flask url_map against SCAFFOLD.yaml `endpoints[]`: 56 declared vs 57 registered — zero missing, one extra: Flask's built-in `GET /static/<filename>` route. Fixed `workspace/implementation/app.py:11` to `Flask(__name__, static_folder=None)` so unknown paths fall through to the envelope-shaped 404 handler. Re-verified after the edit: 56 registered, 56 declared, zero missing, zero extra. `bash -n start.sh` clean; `prd-bench-local-run` present at /usr/local/bin.

## Step 7: Run tests and iterate — 2026-08-11T14:43:05.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).

**Sweep results:**
- Iteration 1: 67–68/75 per round. Union of failures: 8 tests (5 deterministic NameErrors + intermittent server-lifecycle errors on report/invoice tests).
- Iteration 2: **all 8 rounds 75/75 passed, 0 failed, 0 errors.** (Orchestrator re-verified all 8 `results.{i}.json` on disk: passed=75 total=75 failed=0 errors=0 in every round.)

**Tests deleted:** none. Every failing test traced to PRD-covered, uniquely-derived rules; all failures were test-artifact bugs or infrastructure timing, so nothing met the deletion bar.

**Fixes applied to `test_suite/`:**
- `test_04_case_lifecycle.py` — added missing imports `setup_scenario` and `create_confirmed_schedule` (used by `test_case_posture_advances_through_report_phase` and `TestCommittedVsActuals._setup_dual_variant_scenario`; both exist in `test_helpers/fixtures.py` but weren't imported — pure test bug).
- `test_05_reports_and_documents.py` — added missing import `fund_retainer` (used in the privilege-gate test).
- `test_10_cascades_and_evaluations.py` — added missing import `setup_active_engagement` (used by both `TestTerminationCascade` tests).

**Fixes applied to `test_helpers/`:**
- `api_client.py` — `ApiClient.__init__` now sets `self.session.headers["Connection"] = "close"`. Root cause of the intermittent `RemoteDisconnected` / "could not be restarted" errors: the runner kills and respawns the server before every test (per-test-server isolation) while the framework's session-scoped `requests.Session` holds keep-alive connections; under 8x concurrent-round load a stale pooled connection occasionally raced the kill. A quiet-window 30-iteration restart loop reproduced 0 failures, confirming load-only timing. The fix is connection-level resilience only — no assertion, fixture precondition, or payload changed.

**Fixes applied to `implementation/`:** none. The implementation was correct throughout; all sweep failures traced to the test artifact layer.

## Step 8: Finalize PRD — 2026-08-11T14:51:19.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 340 lines; PRD_FINALIZED.md: 343 lines; delta +3 lines (+0.88%).

## Changes (2 edits, one logical fix)
- **§2.2 Standard Error Response Format — insert** — added one sentence pinning that an unexpected internal failure (any exception escaping endpoint processing) is answered in the standard error envelope with `error_id` `ERR_INTERNAL` and HTTP status 500 — `implementation/app.py:53-58`.
- **§5 Error Code Catalogue — insert** — added row `ERR_INTERNAL | 500 Internal Server Error`, keeping the section's "enumerates every error identifier" claim true against the implementation — `implementation/app.py:58`.

## Per-item reasoning for the rest of `<step_7_diff>` (no edit)
- `test_04` / `test_05` / `test_10` import fixes — pure test bugs: `setup_scenario`, `create_confirmed_schedule`, `fund_retainer`, `setup_active_engagement` all exist in `test_helpers/fixtures.py` (lines 97, 113, 155, 227); the tests merely failed to import them. No PRD silence.
- `api_client.py` `Connection: close` header — transport-level keep-alive resilience under per-test-server restarts; no assertion, fixture, or payload changed. HTTP connection management is outside PRD scope by design.
- Pre-Step-7 `static_folder=None` fix — checked all three handlers per the scope note:
  - **404 (undeclared paths)**: already pinned — §2.2 pins the envelope for "All error API responses (4xx status codes)" and the §5 catalogue (claiming exhaustiveness) provides exactly one 404 id, `ERR_NOT_FOUND`. No edit.
  - **405**: envelope shape pinned by the same universal 4xx sentence; a wrong-method request on a declared path is neither an "undeclared path" nor an "unexpected failure" under the scope note's framing. No edit.
  - **500**: genuinely unpinned — §2.2 is explicitly 4xx-scoped and `ERR_INTERNAL` appears nowhere in the PRD. This was the sole edit warranted.

## Pre-edit search log (NO-NEW-MISMATCH RULE)
- **Edit subject**: error envelope for unexpected/unhandled server failures; error-catalogue exhaustiveness.
- **Impl paths enumerated and read/grepped**: `app.py:41-58` (all four error handlers), `lib.py:36-49` (`ok`/`error_response` envelope builders), `lib.py:52-74` (all `ApiError` factories), `db.py:29-39` (`parse_iso` `ValueError`, caught at both call sites: `lib.py:189-195` `req_dt` and `routes_clock.py:14-17`), full-impl grep for every `ERR_*` id (30 distinct: the 29 catalogued + `ERR_INTERNAL`, used only at `app.py:58`), full-impl grep for `raise`/`errorhandler`/`abort` (only `ApiError` raises and the four `app.py` handlers exist), all `routes_*.py` (business errors exclusively via `ApiError`).
- **Wording adjustment**: scoped the sentence to "unexpected internal failure ... any exception that escapes endpoint processing" so it does not capture (a) the 404/405 handlers, which are dedicated handled rejections with their own ids, nor (b) any `ApiError` business error governed by §2/§3 rules and the catalogue. The `message` text was deliberately left unpinned (the impl's 500 message embeds the exception string, and the PRD's standing convention treats `message` as a free human-readable field). The catalogue row matches the impl exactly (500).

## Step 9: Complete PRD — 2026-08-11T15:00:02.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1181_expert_witness_sourcing_engagement/workspace/PRD_COMPLETED.md` is written.

**Source vs completed:** PRD_FINALIZED.md 343 lines / 52,409 chars → PRD_COMPLETED.md 343 lines / 55,012 chars (char-delta +2,603). All changes are in-paragraph inserts; no sections added, no lines added or removed.

**Counts:** 16 ambiguity-pins, 1 mismatch-revision (the §2.11 validation ladder, which as written placed role authorization strictly before all business rules, contradicting impl's payload-intrinsic checks firing first — revised to pin impl's actual order).

Change log:

- §2.2 — insert — ambiguity — unsupported-method requests rejected `ERR_INVALID_REQUEST` at HTTP 405 — implementation/app.py:49-51
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400 — implementation/lib.py:215-233
- §2.4 — insert — ambiguity — recomputation that changes no stored value performs no write and does not bump `version`/`updated_at` — implementation/services.py:58-64, 154-169
- §2.11 — revise — mismatch — payload-intrinsic rules (trial_date vs report_deadline ordering, case_number uniqueness, invoice period interval at original submission) enforced with the body-shape step, ahead of role authorization — implementation/routes_cases.py:33-37, implementation/routes_invoices.py:67-71
- §3.2 — insert — ambiguity — conflict check starts with `resolution_rationale` empty; credential review starts with `daubert_notes` empty — implementation/routes_screening.py:82, 146
- §3.3 — insert — ambiguity — proposal payload optional; `hourly_rate_cents` on the initial DRAFT→PROPOSED proposal is ignored — implementation/routes_engagements.py:159-168
- §3.3 — insert — ambiguity — `counter_rate_cents` validated but not recorded on the engagement — implementation/routes_engagements.py:175-185
- §3.3 — insert — ambiguity — zero-amount funding payments permitted; zero-retainer engagement activates on a zero payment — implementation/routes_engagements.py:209, 214-223
- §3.3 — revise — ambiguity — amendment field bounds mirror creation bounds, and amendment against CLOSED/TERMINATED is rejected `ERR_INVALID_STATE` (pins "posture where terms remain meaningful") — implementation/routes_engagements.py:233-239
- §3.3 — insert — ambiguity — engagement list for an `Expert` caller is implicitly restricted to that expert's own engagements before filters — implementation/routes_engagements.py:140-141
- §3.5 — insert — ambiguity — opening a report carries no engagement-status precondition — implementation/routes_reports.py:33-43
- §3.5 — insert — ambiguity — review `notes` accepted but not recorded on the report — implementation/routes_reports.py:106
- §3.6 — insert — ambiguity — `estimated_hours` may be fractional; per-venue session list returns sessions in any status — implementation/routes_schedules.py:72, 118-124
- §3.6 — insert — ambiguity — cancellation `reason` accepted but not recorded; `actual_hours` zero-or-more and fractional; completion before `end_at` rejected `ERR_INVALID_STATE` — implementation/routes_schedules.py:159-160, 196-202
- §3.7 — insert — ambiguity — invoice submission has no engagement-status precondition; `hours` fractional; empty `line_items` permitted regardless of travel expense; negative declared `total_cents` fails body validation 400 before the mismatch comparison — implementation/routes_invoices.py:44-47, 64-81
- §3.7 — insert — ambiguity — `new_budget_cents` strictly positive, no comparison against spend already incurred — implementation/routes_cases.py:65-77
- §3.7 — insert — ambiguity — resubmission carries no period fields; the interval rule re-validates the invoice's recorded period — implementation/routes_invoices.py:199

Everything else in the implementation (endpoint set, role tables, state machines, seven-gate engagement-creation order, invoice rounding order and worked example, retainer ledger evaluation order, cancellation-fee window strictness, overlap geometries, termination cascades, probation cascade, OCC guards, error catalogue) was already uniquely pinned by PRD_FINALIZED.md and left unchanged.

## Step 7: 8-round parallel sweep iteration — 2026-08-11T14:45:00.000Z

**Iteration 1 sweep:** 67-68/75 per round. Union of failures: 5 deterministic `NameError`s (missing names in test-file import lists) + intermittent `RemoteDisconnected` / "could not be restarted" lifecycle errors on test_05/test_07 tests.

**Diagnosis:**
- `NameError`s: test files used helpers (`setup_scenario`, `create_confirmed_schedule`, `fund_retainer`, `setup_active_engagement`) that exist in `test_helpers/fixtures.py` but were absent from the files' import lists. Test bugs in `test_suite/`.
- `RemoteDisconnected`/`could not be restarted`: 0/30 reproductions in a quiet restart-loop; the runner kills+respawns the server before every test while the framework's session-scoped `requests.Session` holds keep-alive connections — a stale-pooled-connection race that only fires under 8x concurrent-round load. Fixed client-side in `test_helpers/api_client.py` (`Connection: close` on the session) — connection-level resilience only; no assertion changed.

**Fixes:**
- `test_suite/test_04_case_lifecycle.py`: added `setup_scenario`, `create_confirmed_schedule` to imports.
- `test_suite/test_05_reports_and_documents.py`: added `fund_retainer` to imports.
- `test_suite/test_10_cascades_and_evaluations.py`: added `setup_active_engagement` to imports.
- `test_helpers/api_client.py`: `ApiClient.__init__` sets `session.headers["Connection"] = "close"`.
- No tests deleted; no implementation changes needed.

**Iteration 2 sweep:** all 8 rounds 75/75 passed, 0 failed, 0 errors. Clean 8-round sweep achieved.
