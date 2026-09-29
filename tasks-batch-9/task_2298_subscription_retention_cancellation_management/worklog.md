# Worklog — task_2298_subscription_retention_cancellation_management

## Step 1: Create task directory — 2026-09-01T14:46:09.318Z

Created `tasks/task_2298_subscription_retention_cancellation_management/` and `workspace/` (bash only, no subagent). Directory name was pre-allocated by the caller; no index scan performed.

## Step 2: Generate scaffold (prd-bench-scaffold-generator) — 2026-09-01T16:22:59.313Z

Done. All three artifacts are complete and the lint is clean.

**Verdict block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2298_subscription_retention_cancellation_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2298_subscription_retention_cancellation_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2298_subscription_retention_cancellation_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  895

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/`)
- `SCAFFOLD.yaml` — 2895 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1763 lines, single root key
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4380 lines, single root key

**Counts**
- 14 entities, 8 state machines, 2 OCC concurrency rules, 10 calculations, 48 ordered validations, 51 endpoints, 59 error ids, 5 roles (Subscriber, RetentionSpecialist, BillingOperator, ComplianceOfficer, PlatformAdmin), 11 global constants.
- §1.8: 9 rule_ids × 2 = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: 71 real instances + 24 `excluded_because` stubs = 95 rows across all nine legal sections (entities 13, state_machines 8+5, calculations 7+5, validations 7+3, endpoints 5, errors 22+9, rbac 5, complexity layers 3+2, consistency model 1).

**Notable design decisions**
- Difficulty pushed past "expert" via a 48-rung validation ladder whose adjacent rungs are deliberately co-violable: two `priority_pair_validation_conflict` instances (offer-expiry state vs. margin-floor fiscal; renewal-reminder safety vs. payment-method referential) each assert both the masked and the control outcome.
- Two independent dual-variant surfaces: LTV realized vs. projected (channel base churn × tenure multiplier, 24-cycle cap) and save-offer margin per-cycle vs. blended-term against the plan floor, with a ComplianceOfficer margin-exception workflow gated by segregation of duties on `presented_by_user_id`.
- Dunning is a pinned-order pipeline (tenure-bucketed base grace → card-updater extension → decline-code backoff → strict grace clamp → finality), which makes `is_final`, `grace_clamped` and `ERR_DUNNING_ATTEMPTS_EXHAUSTED` mutually reachable only through specific decline codes (`LOST_STOLEN` backoffs `[0,0,0,0]`).
- Subscription state is two parallel axes (lifecycle × billing) so PAUSED-while-PAST_DUE is legal and gates offer acceptance.
- `save_offer_selection` intentionally keeps quota-exhausted templates in the candidate set so priority 39 (`ERR_OFFER_QUOTA_EXCEEDED`) cannot degenerate into priority 40 (`ERR_NO_ELIGIBLE_SAVE_OFFER`).
- Two OCC rules only (`expected_subscription_version`, `expected_campaign_version`); OCC outranks the lapse and launch checks, which the layers section asserts explicitly.
- Only two test-driving endpoints (`POST /_clock/set_current_utc`, `POST /_payments/simulate`); everything else is a business endpoint.

Incidental fixes made while validating: added the two missing typed 404s (`ERR_DUNNING_ATTEMPT_NOT_FOUND`, `ERR_COHORT_SNAPSHOT_NOT_FOUND`), quoted 97 optional-input tokens (`foo?`) and 44 `$.data[N].id` capture paths that PyYAML rejects inside flow collections, and added `payment_method_id?` to `GET /subscriptions` to satisfy FK reverse-reachability. No sibling task directory was inspected at any point.

## Step 3: Copy shared files — 2026-09-01T16:23:04.417Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD (prd-bench-doc-generator) — 2026-09-01T16:37:52.525Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/workspace/PRD.md`.

## Deliverable
- **502 lines**, no audit footer (file ends with the §5 table).
- Sources read: `SKILL.md`, `section-2.2-response-structure.md`, `example-prd.md`, and `SCAFFOLD.yaml` (2896 lines, read in full via three paginated calls). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was inspected.

## Section structure
- §1 Introduction (3 paragraphs, framing the voluntary/involuntary churn split, the simple-cancellation guarantee, and segregation of duties).
- §2 Global Specifications, 11 subsections: 2.1 RBAC · 2.2 Response Structure (verbatim) · 2.3 Pagination · 2.4 Identity/Timestamps/Logical Clock · 2.5 Nested Retrieval & Existence Ordering · 2.6 Validation Ordering (9 bands) · 2.7 OCC · 2.8 Money/Margins/Rounding · 2.9 Two Conserved Quantities · 2.10 Two Independent Subscription Axes · 2.11 Negative-Option Compliance.
- §3 Business Logic, 9 subsections: 3.1 Catalogue · 3.2 Registration & Signup · 3.3 Modifications · 3.4 Invoicing & Renewal Run · 3.5 Cancellation Conversation · 3.6 Save Offers & Margin Exceptions · 3.7 Collections/Dunning · 3.8 Win-Back · 3.9 Retention Analytics.
- §4 Endpoint Definitions (4-column table, 51 rows).
- §5 Error Code Catalogue (2-column table, 59 rows).

## Coverage audits (all PASS)
- **Contract 1 (field-name coverage): 165/165 required identifiers present verbatim in backticks, 0 missing** — 151 entity fields, 79 body inputs, 22 query/path params, 2 OCC fields (deduped to 165 unique). Also verified: 0 enum members missing across every entity field; every non-trivial field default present (the one script flag, `allowed_frequency_weeks` `[2, 4, 8]`, is stated in prose as "the three values 2, 4 and 8").
- **Contract 2 (rule coverage): 0 gaps.** All 48 validations rendered with per-endpoint evaluation order (including the 9 multi-endpoint `applies_to` scopes, e.g. priority 6 ownership across all 9 endpoints, priority 17/20/24/28/33/34/48 across both of their targets); both `concurrency_rules` with their structural justification; all 48 transitions across 8 machines (both Subscription axes, plus the grant's independent margin-exception axis) with source/target states named; all 10 calculations translated into operator-free prose, with both branches of each of the 3 dual-variant pairs (invoice FULL_CYCLE/MID_CYCLE_REPRICE, margin PER_CYCLE/BLENDED_TERM, LTV REALIZED/PROJECTED) and their divergence made explicit; all 11 global constants embedded as literals; sibling-branch symmetry covered (accept vs. decline, ACTIVE vs. PAUSED write-off cascade, scheduled vs. applied reversal).
- **Contract 3 (§3 path purity): 0 violations** — no backtick token in §3 starts with `/`, is a bare HTTP method, or combines method+path. The single nested read path appears only in §2.5.
- **§4/§5 exactness:** 51/51 endpoints match method+path exactly with 0 extras and 0 role mismatches (5-role sets collapsed to "Any authenticated role" per the note in §4); 59/59 error IDs match with 0 HTTP status mismatches.
- **§2.2 verbatim:** byte-for-byte identical to `section-2.2-response-structure.md`.

## Two scaffold ambiguities resolved in prose
1. **Dunning backoff indexing** — `BACKOFF_DAYS_BY_DECLINE[...][attempt_number - 1]` admits 0- and 1-based readings. Pinned as: the position whose ordinal (counting from 1) equals the *previous* attempt's `attempt_number`, so attempt 2 uses the first element, attempt 4 the third; the fourth element is unreachable given the retry ceiling of 4.
2. **Renewal-run guard ordering** — the global priority table ranks 26 `ERR_RENEWAL_REMINDER_MISSING` above 32 `ERR_RENEWAL_NOT_DUE` above 48 `ERR_PAYMENT_METHOD_INACTIVE`, while the endpoint's side_effects put the negative-option gate at step 5. Rendered as: the due check fires before anything is mutated, then steps 1–7 with the reminder gate at step 5 (nothing mutated on failure) and the payment-method check at step 7, plus an explicit note that the gate is vacuous when the run will not issue an invoice (PENDING_CANCEL finalisation, non-negative-option plan, or skipped cycle).

## Step 5: Generate unit tests (prd-bench-unit-test-generator) — 2026-09-01T17:55:33.344Z

Suite is complete. Final state under `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/`:

## Files written

**`test_helpers/` (9 files)** — `__init__.py` (re-exports the pip-installed `prd_bench_local_runner.testing` surface plus everything local), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (`ApiErrorId`, `HTTP_STATUS_CODES`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/` (conftest + 36 test files, `test_01_`…`test_36_`)** — queue A in `test_01_`–`test_17_`, queue B in `test_18_`–`test_36_`. Files added in this final stretch: `test_35_optimistic_concurrency_layers.py` (3 tests — the three `cross-cutting complexity layers` instances) and `test_36_derived_price_visibility.py` (1 test — the `consistency model` instance).

## Test counts

| Queue | Source | Instances | Tests |
|---|---|---|---|
| A | §1.8 difficulty index | 18 non-stub (18 total) | **36** (2 per instance) |
| B | §1.9 corner index | 71 non-stub (95 total, 24 stubs) | **71** (1 per instance) |
| | | | **107 total** |

Queue B by section: entities 13, state_machines 8, calculations 7, validations 7, endpoints 5, errors 22, rbac 5, cross-cutting complexity layers 3, consistency model 1.

## Instances translated vs skipped

- **Translated: 89/89 non-stub instances (18 A + 71 B). Zero instances skipped** — every one passed the PRD-first two-condition filter (verbatim PRD sentence naming the rule + PRD uniquely deriving the asserted outcome).
- **24 `excluded_because:` stubs emitted nothing**, as required; all 24 cross-references were machine-verified to resolve to a real §1.8 instance name.

## Audit results

- **Coverage audit**: 107 tests / 107 `Design:` tags, 1:1 in every file. All tags resolve to an existing instance; no tag points at a stub; no queue-A instance has fewer than 2 tests; no non-stub queue-B instance is missing.
- **Docstring-tag discipline**: all 107 docstrings audited — exactly one `Design:` line each, and it is the final non-blank line. No dual-tagged or untagged tests.
- **PRD-citation pass**: 112 quoted PRD sentences extracted and literal-matched (whitespace-normalised) against `workspace/PRD.md` — **0 misses**.
- **Scaffold-citation pass**: no occurrence of "scaffold", "§1.", or design-file names anywhere in `test_suite/` or `test_helpers/`.
- **Hygiene**: `py_compile` clean; `pyflakes` clean over `test_suite/` (the only warnings are the intentional re-export lines in `test_helpers/__init__.py`). No `pytest.skip`, `xfail`, mocking, or placeholder tests anywhere.

## Design-vs-PRD divergences (PRD figure asserted, with an inline arithmetic comment)

Five design assertions contradicted a value the PRD uniquely derives; in each case the PRD number was asserted: the attempt-3 dunning backoff (3, not 5) in `dunning_schedule_pinned_step_order_extension_then_clamp`, the do-not-contact win-back `priority_score` (0.5475 = 0 + 0.30×(1 − 1/120) + 0.25, not 0.5500), plus the previously noted corrections in `winback_target_cycles_back_to_eligible_and_resends` and `write_off_cascade_invoice_subscription_subscriber_session`. Additionally, in `subscription_version_increments_once_per_write_including_indirect_ones` the design's `cancel_effective_at == 2026-03-07T00:00:00Z` presumes a cadence change retroactively moves the *already-set* `next_renewal_at`, which PRD §3.3 line 218 does not settle — so that test asserts `cancel_effective_at` equals the `next_renewal_at` read immediately before completion (the rule the PRD does state), leaving the instance's version-counting claim fully asserted. Separately, the reverse-modification endpoint's success status is not PRD-derivable (§4 makes it both a creation and a mutation), so reverse calls go through the lenient `get_success_data` rather than pinning 200 or 201.

## Step 6: Generate implementation (prd-bench-implementation-generator) — 2026-09-01T17:55:33.344Z

All three smoke suites now pass end to end and the test servers are stopped. Final state of the work:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/workspace/implementation/` (20 files, nothing else on disk — only `__pycache__`):

- Top level: `app.py`, `constants.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `serializers.py`, `requirements.txt` (`flask>=3.0`), `start.sh` (executable)
- `services/`: `__init__.py`, `calc.py` (pure arithmetic: money/fraction rounding, tenure buckets, relation lookups, LTV, offer margins, win-back score), `ops.py` (domain procedures: invoice build/reprice, renewal run, dunning schedule, settlement cascade, modification apply/reverse, offer selection, suppression predicates)
- `routes/`: `__init__.py` (list filtering + pagination helper), `catalog.py`, `people.py`, `subscriptions.py`, `billing.py`, `cancellation.py`, `winback.py`, `analytics.py`

**51 endpoints**, exactly matching the PRD §4 table (verified row count). State is in-memory dicts only, empty on every boot (confirmed: every listable collection returns `total_count: 0` on a fresh process; `GET` on `/subscribers`, `/save-offer-templates`, `/winback-campaigns` correctly 405s since §4 declares no list route for them). `start.sh` boots from any cwd, honours `PORT` (default 10000), and `exec`s python so the harness's kill hits the server directly.

## Verification
Three scripted suites (~150 assertions) against fresh boots, all green, no tracebacks or 500s in the server log. Pinned PRD numbers reproduced exactly: committed 4093 for 4999+1299 at 35% off; signup invoice 6298/2600 with `["PLAN","EXTRA"]` line order; mid-cycle reprice 0.75 → 2249/900; save-offer margins 0.3536/0.5115 with retention value 10995, deep-discount −1.1/0.2999, PAUSE 0.0000/0.5799; LTV realized 7396 / projected 29584 (PAID_SOCIAL × M0_1 = 0.16 → 6 cycles); grace 3 days then +4 with card-updater PENDING, clamp ⇒ `is_final`, retry ceiling at 4; write-off cascade → DELINQUENT/CANCELLED/INVOLUNTARY + 30-day suppression + session abandonment; win-back score 0.1330 with the involuntary 0.4000 ceiling in place; notice window/cooldown guards; and a rollback check proving a rejected renewal mutates nothing.

## Interpretation decisions where the PRD was ambiguous
1. **Transactionality**: a per-request deepcopy snapshot taken in `before_request` and rolled back in the error handlers, with `threaded=False`, so any multi-step operation that fails mid-way (renewal run step 5, offer acceptance) leaves zero mutations.
2. **Ordering ties**: an internal monotonic `_seq` breaks `created_at` ties for list ordering and "most recent" lookups; all `_`-prefixed internals (`_seq`, `_suppression_grant_id`) are stripped from JSON.
3. **Derived-at-read**: subscriber tenure/LTV/`save_offer_grants_365d_count`/`last_contacted_at`, `Plan.active_subscription_count`, campaign counters and `term_shipments_remaining` are computed on read, which satisfies every "recomputed whenever…" clause by construction.
4. **Modification type fields**: the scaffold marks them all optional, so a missing/invalid `frequency_weeks`, `addon_code`, `target_plan_id` etc. surfaces as the pinned domain 422 (or a default) rather than a schema 400.
5. **PAUSE/SKIP offer acceptance** applies its lever through §3.3 semantics, so accepting a PAUSE offer does move `lifecycle_state` to `PAUSED` (window = clock → clock + `pause_cycles` × cycle days, `paused_until` = `next_renewal_at` = window end). §3.6's "lifecycle_state left exactly as it was" is read as referring to the cancellation axis only, matching the scaffold's "creates a SubscriptionModification of the offer's lever … mutating the Subscription".
6. **Offer margin math** uses plan list price only (no addons), per §3.6's wording, even when the subscription carries addons.
7. **Cohort snapshot** `plan_code` filter matches the plan of the subscriber's earliest subscription (PRD doesn't say which), and the cohort month window is half-open `[month start, next month start)`.
8. Unknown body fields are ignored; `api_request_timestamp` is the only wall-clock value, everything else reads the logical clock.

## Step 7: Run tests and iterate — 2026-09-01T18:06:57.515Z

All 8 parallel rounds pass 107/107.

## Summary

**Iterations run:** 2 sweeps of 8 parallel rounds (sweep 1: 104/107 in all 8 rounds; sweep 2: 107/107 in all 8 rounds). No flakiness observed — the failures were deterministic and identical across all 8 rounds both times.

**Tests deleted:** none. All 3 failing tests survived STEP 1 (coverage + unique derivability).

**Fixes applied to `test_helpers/`:** none — the fixtures/factories were consistent with the PRD; the shared failure traced to a single implementation decision, not an upstream fixture bug.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/test_suite/test_11_price_conservation.py` — `test_the_delta_ledger_still_reconstructs_the_committed_price_after_a_reversal` previously read `state == "REVERSED"` / `delta_price_cents == -4198` off the `/reverse` *response body*. PRD §3.3 line 224 states only that the SCHEDULED branch "returns it"; it never names what the APPLIED branch returns, so that dependency was not uniquely derivable (STEP 1c partial coverage). The two PRD-verbatim assertions are kept, now made against an explicit `GET /subscription-modifications/{id}` re-read (added `read_modification` import) instead of the unstated payload.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2298_subscription_retention_cancellation_management/workspace/implementation/routes/subscriptions.py`, `reverse_modification()` — both branches returned `created(...)` (201). PRD §4 line 384: "Operations that bring a new resource into existence return `201 Created`. Operations that modify, settle or advance an existing resource return `200 OK`." `/subscription-modifications/{id}/reverse` is path-scoped to an existing modification and §4 describes it as "Reverse an applied modification, or cancel a scheduled one" — a mutation of an existing resource in both branches (the SCHEDULED branch creates nothing at all, so 201 is untenable there, and PRD declares no per-branch status split). Changed both branches to `ok(S.modification(mod))`, returning the target row per the PRD's one explicit statement ("sets that row to `CANCELLED` and returns it"). This also matches the PRD's own internal precedent: save-offer accept (§3.6 line 308) likewise creates a `SubscriptionModification` as a cascade yet is a settle on the existing grant and returns 200 with the grant. The compensating row is still created and still discoverable via the `reverses_modification_id` list filter (§3.3 line 226), which is how every test reaches it.

## Step 8: Finalize PRD — 2026-09-01T18:09:37.538Z

`PRD_FINALIZED.md` written with a single edit.

**Line counts:** PRD.md 502 lines → PRD_FINALIZED.md 502 lines (0 lines added/removed; one sentence extended in place, +0.0% line delta, ~+470 chars).

**Changes**
- §3.3 (Reversal, line 224) — revise — extended the closing sentence of the Reversal paragraph so it now pins both the status code and the response body of `POST /subscription-modifications/{id}/reverse` for *both* branches: `200 OK` carrying the targeted modification row itself (the row just set to `CANCELLED`, or the original now in `REVERSED` with its `delta_price_cents` left intact), never the compensating row, "even though the `APPLIED` branch does bring that compensating row into existence"; the compensating row remains reachable via the `reverses_modification_id` list filter — `implementation/routes/subscriptions.py:343-348` (SCHEDULED branch) and `:378-394` (APPLIED branch).

**Pre-edit search log (edit 1)**
- (a) Subject: the HTTP status and response payload of the reverse endpoint, and by extension §4's 201-vs-200 classification wherever an operation's cascade creates rows.
- (b) Paths enumerated/read: `routes/subscriptions.py:331-394` (`reverse_modification`, both branches → `ok(S.modification(mod))`); `response.py:52-63` (`ok`/`created` — `created` is just `ok(..., 201)`); a full grep of every `return created(...)` / `return ok(...)` / `send_list` site in `routes/` (billing, cancellation, catalog, people, subscriptions, winback, analytics) to confirm the classification invariant actually held by the impl — every `created()` returns a resource minted by that same call (plans, templates, subscribers, payment methods, subscriptions, modifications, scheduled notices, dunning attempts, sessions, presented grants, campaigns, targets, snapshots), and every mutating `ok()` returns a resource that already existed (PATCH subscriber, updater-result, renewal run `ok(subscription)` while creating an invoice/notice, send-notice, reason capture, complete, `accept_grant` `ok(grant)` at `cancellation.py:221` while creating an `APPLIED` modification, decline, margin-exception, launch, target send, reevaluate, `_clock` → `ok({})`, `_payments/simulate` → `ok(attempt)`); `serializers.py:129-137` (`MOD_FIELDS`, confirming the returned row exposes `state`, `delta_price_cents`, `reverses_modification_id`); `db.py:87-91` (`touch` bumps `version`, so the returned row is post-bump); `services/ops.py:258-280` (`new_modification` — compensating row's `reverses_modification_id`, never returned in the body); `routes/subscriptions.py:403-411` (the `reverses_modification_id` list filter that reaches it).
- (c) Wording adjustments made: I first drafted a general clarification in §4 ("an operation path-scoped to an existing resource returns 200…"), then discarded it — the enumeration showed `POST /subscriptions/{id}/modifications`, `/subscriptions/{id}/compliance-notices`, `/invoices/{id}/dunning-attempts`, `/cancellation-sessions/{id}/present-offers` and `/winback-campaigns/{id}/targets` are all path-scoped to an existing parent yet return `201`, so that phrasing would have been a brand-new mismatch. I also dropped a candidate "notwithstanding the general rule of §4" cross-reference in favour of the local "even though the `APPLIED` branch does bring that compensating row into existence", which keeps the override scoped to this one endpoint and leaves §4 line 384 and the 200-returning cascade endpoints (accept, complete, renewal run) untouched and still accurate.

No edits traced to the `test_suite/test_11_price_conservation.py` change beyond this one — it targets the same subject (what `/reverse` returns), now pinned; the Step 7 report lists no `test_helpers/` fixes and no test deletions, so nothing else required a patch.

## Step 9: Complete PRD — 2026-09-01T18:25:26.806Z

Done. `PRD_COMPLETED.md` is written and complete.

**Counts**
- Source `workspace/PRD_FINALIZED.md`: 502 lines / 96,588 chars
- `workspace/PRD_COMPLETED.md`: 502 lines / 106,799 chars (**char delta +10,211**; line count unchanged — every change is in-paragraph, no new paragraphs or sections)
- **49 changes: 37 ambiguity-pins, 12 mismatch-revisions**

**Changes**
- §2.1 — revise — mismatch — subscriber ownership is enforced only on the band-6 write endpoints; every read/list endpoint is unscoped (was "its reads are scoped to its own resources") — `middleware.py` (`own` called only in write handlers, e.g. `routes/subscriptions.py:43,162`) vs `routes/subscriptions.py:126`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `response.py:26`
- §2.3 — insert — ambiguity — empty `limit`/`offset` treated as absent; non-integer, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` 400; unknown/empty filters ignored; filters never match null fields — `response.py:87`, `routes/__init__.py:15`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order, and that tie-break resolves every otherwise-undetermined ordering — `db.py:94`
- §2.4 — revise — ambiguity — `to_iso8601` required, clock may move backwards, responds 200 with empty `data` — `routes/analytics.py:100-106`
- §2.8 — revise — ambiguity — 4-dp fractions are emitted as JSON numbers, so `0.3500` renders `0.35` — `response.py:30`
- §2.9 — revise — ambiguity — `term_shipments_remaining` derived per read from the *current* plan's `shipments_per_term` — `serializers.py:83`
- §2.10 — insert — ambiguity — a rejected request persists nothing: all intermediate mutations (incl. dunning grace recomputation) are rolled back — `app.py:26-36`
- §2.11 — revise — ambiguity — upcoming cycle index = max existing `cycle_index` + 1, and 0 with no invoices — `services/ops.py:124`
- §2.11 — revise — ambiguity — out-of-window `renewal_reminder_days_before` is a schema-band `ERR_INVALID_REQUEST`; window read against live `next_renewal_at` — `routes/subscriptions.py:271-275`, `services/ops.py:152`
- §2.11 — insert — ambiguity — notice cooldown is scoped to the same subscription — `routes/subscriptions.py:293-302`
- §3.1 — revise — ambiguity — duplicate/malformed plan `code` → `ERR_INVALID_REQUEST` 400 — `routes/catalog.py:19`
- §3.1 — revise — ambiguity — `addon_catalog` entry shape (all three fields, ≥0 bounds) and which plan fields are required vs defaulted — `routes/catalog.py:19`
- §3.1 — revise — ambiguity — duplicate template `code` → `ERR_INVALID_REQUEST` 400 — `routes/catalog.py:96`
- §3.1 — revise — ambiguity — template required inputs (`code`,`name`,`offer_type`,`priority_rank`), enum membership of `eligible_reason_codes`, ≥0 bounds — `routes/catalog.py:96`
- §3.2 — revise — ambiguity — duplicate subscriber `email` → `ERR_INVALID_REQUEST` 400; `do_not_contact` required in the preference update — `routes/people.py:25,49`
- §3.2 — revise — ambiguity — `frequency_weeks` must be a positive integer; `disclosure_acknowledged` stored and echoed; addon entry object shape with `qty` default 1 — `routes/subscriptions.py:34-41`
- §3.2 — revise — ambiguity — signup notices are created with `scheduled_for` null (disclosure), `EMAIL` channel, null `body_ref` — `routes/subscriptions.py:102-105`
- §3.2 — revise — ambiguity — a non-qualifying `winback_target_id` is silently ignored (signup still succeeds); conversion bumps the campaign's `version` — `routes/subscriptions.py:109-120`
- §3.3 — insert — ambiguity — `DISCOUNT_APPLY` accepts `discount_pct`/`discount_cycles` but never echoes them on the modification row; `pause_start_at`/`pause_end_at`/`skip_ship_at` defaults — `routes/subscriptions.py:151-178,228-230`
- §3.3 — insert — ambiguity — a missing type-specific input falls into its own domain rejection, not the schema band; addon removal validates against the plan catalogue, not held addons — `routes/subscriptions.py:196-216`
- §3.3 — revise — mismatch — `paused_until` is cleared whenever a `RESUME` modification applies (including out of `SCHEDULED`), as opposed to the renewal run's own auto-resume which leaves it alone — `services/ops.py:199`
- §3.3 — revise — mismatch — downgrade repricing targets the most recently created `OPEN` invoice, and the `PRICE_CHANGE` notice is created unconditionally, whether or not an `OPEN` invoice existed — `services/ops.py:97,199`
- §3.3 — revise — ambiguity — compensating row's copied fields/`applied_at`/`prior_snapshot`, and the exact per-`mod_type` field sets the supersession check compares (`PAUSE`/`RESUME` touch nothing) — `routes/subscriptions.py:319-376`
- §3.4 — insert — ambiguity — invoice line shape: `kind` PLAN then ADDON, plan line's undiscounted `unit_price_cents` and `qty` = `shipments_per_cycle`, no per-line COGS — `services/ops.py:44`
- §3.4 — insert — ambiguity — a null `next_renewal_at` also skips the due check — `services/ops.py:338`
- §3.4 — revise — mismatch — step 4 recomputes `committed_price_cents` only; no invoice is re-priced there (was "the cycle is re-priced") — `services/ops.py:338`
- §3.4 — revise — mismatch — on a skipped cycle `next_ship_at` advances in step with `next_renewal_at` (was "runs one further cycle ahead"), and no counters/discount/reminder move — `services/ops.py:338`
- §3.5 — insert — ambiguity — `reason_code` is required — `routes/cancellation.py:70`
- §3.5 — revise — ambiguity — `confirm` is required but its value gates nothing (`false` cancels); confirmation notice has null `scheduled_for` and the upcoming `renewal_cycle_index` — `routes/cancellation.py:139-160`
- §3.6 — revise — ambiguity — present-offers takes no request body and returns the grant with 201, not the session — `routes/cancellation.py:89-131`
- §3.6 — revise — ambiguity — quota counting basis (that template only, any subscription, `PRESENTED`/`ACCEPTED`, `created_at` ≥ clock−365d) — `services/ops.py:580-621`
- §3.6 — revise — ambiguity — `justification` is validated but not persisted — `routes/cancellation.py:246`
- §3.6 — revise — ambiguity — offer lever inputs come from the template: discount pair, `pause_cycles` (min 1) × cycle days, skip consumes exactly one unit, downgrade target from the plan — `services/ops.py:623`
- §3.6 — revise — ambiguity — a `PRESENTED` grant can be declined after `expires_at` — `routes/cancellation.py:224-237`
- §3.7 — insert — ambiguity — absent `decline_code` ⇒ 0-day backoff; null `attempted_at` ⇒ the clock anchors the backoff — `services/ops.py:441-451`
- §3.7 — insert — ambiguity — a null `first_failed_at` bypasses grace recompute/`GRACE` transition/grace rejection at *any* `attempt_number`, leaving `grace_clamped` and `is_final` false — `services/ops.py:453-465`
- §3.7 — revise — mismatch — the grace rejection fires only strictly after `grace_end_at`; a retry exactly at `grace_end_at` is permitted — `services/ops.py:464`
- §3.7 — revise — ambiguity — settleable outcome enum (`PENDING` excluded), earliest `PENDING` attempt by `created_at`, `decline_code` discarded on `SUCCEEDED`, response is the `DunningAttempt` — `routes/billing.py:55-70`, `services/ops.py:509-516`
- §3.7 — revise — ambiguity — a `SUCCEEDED` settlement also increments the subscriber's `version` — `services/ops.py:509-545`
- §3.7 — revise — mismatch — an `UPDATED` card-updater outcome forces `status` to `ACTIVE`, restoring even from `REPLACED`/`EXPIRED` (was "keeps status ACTIVE") — `routes/people.py:117-118`
- §3.7 — revise — mismatch — write-off drives `billing_state` to `DELINQUENT` from any prior value including `CURRENT`, increments `consecutive_failed_attempts`, leaves `first_failed_at`/`grace_end_at` untouched, sweeps sessions regardless of age, and leaves churn fields alone when lifecycle was already `PENDING_CANCEL`/`CANCELLED` — `services/ops.py:318-336,553`
- §3.8 — revise — mismatch — `target_channels`/`target_reason_codes` are validated and stored but never consulted at targeting, so they narrow nothing; duplicate `code` and `max_days_since_lapse < min_days_since_lapse` → `ERR_INVALID_REQUEST`; `send_window_days`/`suppression_days` ≥ 0 — `routes/winback.py:24-42` vs `routes/winback.py:78-126`
- §3.8 — revise — ambiguity — launching any non-`DRAFT` campaign, `CLOSED` included, → `ERR_CAMPAIGN_NOT_LAUNCHED` 409 — `routes/winback.py:65`
- §3.9 — revise — ambiguity — `tenure_days` clamps up to 0 when the clock precedes `first_subscribed_at` — `services/calc.py:47-51`
- §3.9 — revise — mismatch — `realized_ltv_cents`/`projected_ltv_cents` are not stored columns recomputed at events; both are derived from invoices on every read — `services/calc.py:143-178`
- §3.9 — revise — ambiguity — `plan_code` is a free-form string never checked against the plan table (unknown ⇒ empty cohort) and members with no subscription are excluded — `routes/analytics.py:36,49-55`
- §3.9 — revise — mismatch — snapshot creation writes only the snapshot row, bumps no `version` anywhere, and computes the mean from the members' invoices (was "reads the two stored lifetime-value fields") — `routes/analytics.py:74-91`
- §4 — revise — mismatch — "Any authenticated role" carries no ownership scoping at all — `middleware.py` (`auth()` with no roles, no `own` call)

Two impl behaviours were deliberately left unpinned because they sit outside the PRD's error catalogue and no PRD prose implies otherwise: unknown route → `ERR_NOT_FOUND` 404 and wrong method → `ERR_METHOD_NOT_ALLOWED` 405 (`app.py:38-47`).
