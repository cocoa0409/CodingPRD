import {
  MarketplaceTenant, Listing, Order, Worker, Assignment, Payout, Dispute, Rating,
  PayoutBudgetLedger, WorkerDebtLedger, WorkerPerformanceLedger, WorkerCapacityLedger,
  IdempotencyRecord, CONSTANTS
} from './types';

const tenantSequences: Map<string, number> = new Map();

export function getNextSeq(tenantId: string): number {
  const current = tenantSequences.get(tenantId) || 0;
  const next = current + 1;
  tenantSequences.set(tenantId, next);
  return next;
}

class Storage {
  tenants: Map<string, MarketplaceTenant> = new Map();
  listings: Map<string, Listing> = new Map();
  orders: Map<string, Order> = new Map();
  workers: Map<string, Worker> = new Map();
  assignments: Map<string, Assignment> = new Map();
  payouts: Map<string, Payout> = new Map();
  disputes: Map<string, Dispute> = new Map();
  ratings: Map<string, Rating> = new Map();

  payoutBudgetLedgers: Map<string, PayoutBudgetLedger> = new Map();
  workerDebtLedgers: Map<string, WorkerDebtLedger> = new Map();
  workerPerformanceLedgers: Map<string, WorkerPerformanceLedger> = new Map();
  workerCapacityLedgers: Map<string, WorkerCapacityLedger> = new Map();

  idempotencyRecords: Map<string, IdempotencyRecord> = new Map();

  getTenant(id: string): MarketplaceTenant | undefined {
    return this.tenants.get(id);
  }

  getAllTenants(): MarketplaceTenant[] {
    return Array.from(this.tenants.values()).sort((a, b) => a.created_seq - b.created_seq);
  }

  saveTenant(tenant: MarketplaceTenant): void {
    this.tenants.set(tenant.id, tenant);
  }

  getListing(id: string): Listing | undefined {
    return this.listings.get(id);
  }

  getListingsByTenant(tenantId: string): Listing[] {
    return Array.from(this.listings.values())
      .filter(l => l.tenant_id === tenantId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  saveListing(listing: Listing): void {
    this.listings.set(listing.id, listing);
  }

  getOrder(id: string): Order | undefined {
    return this.orders.get(id);
  }

  getOrdersByTenant(tenantId: string): Order[] {
    return Array.from(this.orders.values())
      .filter(o => o.tenant_id === tenantId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  saveOrder(order: Order): void {
    this.orders.set(order.id, order);
  }

  getWorker(id: string): Worker | undefined {
    return this.workers.get(id);
  }

  getWorkersByTenant(tenantId: string): Worker[] {
    return Array.from(this.workers.values())
      .filter(w => w.tenant_id === tenantId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  saveWorker(worker: Worker): void {
    this.workers.set(worker.id, worker);
  }

  getAssignment(id: string): Assignment | undefined {
    return this.assignments.get(id);
  }

  getAssignmentsByOrder(orderId: string): Assignment[] {
    return Array.from(this.assignments.values())
      .filter(a => a.order_id === orderId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  getAssignmentsByWorker(workerId: string): Assignment[] {
    return Array.from(this.assignments.values())
      .filter(a => a.worker_id === workerId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  getActiveAssignmentsByWorker(workerId: string): Assignment[] {
    return this.getAssignmentsByWorker(workerId)
      .filter(a => a.status === 'ACCEPTED' || a.status === 'IN_PROGRESS');
  }

  getActiveAssignmentsByOrder(orderId: string): Assignment[] {
    return this.getAssignmentsByOrder(orderId)
      .filter(a => a.status === 'ACCEPTED' || a.status === 'IN_PROGRESS');
  }

  saveAssignment(assignment: Assignment): void {
    this.assignments.set(assignment.id, assignment);
  }

  getPayout(id: string): Payout | undefined {
    return this.payouts.get(id);
  }

  getPayoutsByWorker(workerId: string): Payout[] {
    return Array.from(this.payouts.values())
      .filter(p => p.worker_id === workerId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  getPayoutsByAssignment(assignmentId: string): Payout[] {
    return Array.from(this.payouts.values())
      .filter(p => p.assignment_id === assignmentId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  getPayoutsByTenant(tenantId: string): Payout[] {
    return Array.from(this.payouts.values())
      .filter(p => p.tenant_id === tenantId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  savePayout(payout: Payout): void {
    this.payouts.set(payout.id, payout);
  }

  getDispute(id: string): Dispute | undefined {
    return this.disputes.get(id);
  }

  getDisputesByOrder(orderId: string): Dispute[] {
    return Array.from(this.disputes.values())
      .filter(d => d.order_id === orderId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  saveDispute(dispute: Dispute): void {
    this.disputes.set(dispute.id, dispute);
  }

  getRating(id: string): Rating | undefined {
    return this.ratings.get(id);
  }

  getRatingsByOrder(orderId: string): Rating[] {
    return Array.from(this.ratings.values())
      .filter(r => r.order_id === orderId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  getRatingsByWorker(workerId: string): Rating[] {
    return Array.from(this.ratings.values())
      .filter(r => r.worker_id === workerId)
      .sort((a, b) => a.created_seq - b.created_seq);
  }

  saveRating(rating: Rating): void {
    this.ratings.set(rating.id, rating);
  }

  getPayoutBudgetLedger(tenantId: string): PayoutBudgetLedger {
    let ledger = this.payoutBudgetLedgers.get(tenantId);
    if (!ledger) {
      ledger = {
        tenant_id: tenantId,
        provisional_reserved_cents: 0,
        finalized_paid_cents: 0,
        recovered_clawbacks_cents: 0
      };
      this.payoutBudgetLedgers.set(tenantId, ledger);
    }
    return ledger;
  }

  savePayoutBudgetLedger(ledger: PayoutBudgetLedger): void {
    this.payoutBudgetLedgers.set(ledger.tenant_id, ledger);
  }

  getWorkerDebtLedger(workerId: string): WorkerDebtLedger {
    let ledger = this.workerDebtLedgers.get(workerId);
    if (!ledger) {
      ledger = {
        worker_id: workerId,
        applied_amount_cents: 0
      };
      this.workerDebtLedgers.set(workerId, ledger);
    }
    return ledger;
  }

  saveWorkerDebtLedger(ledger: WorkerDebtLedger): void {
    this.workerDebtLedgers.set(ledger.worker_id, ledger);
  }

  getWorkerPerformanceLedger(workerId: string): WorkerPerformanceLedger {
    let ledger = this.workerPerformanceLedgers.get(workerId);
    if (!ledger) {
      ledger = {
        worker_id: workerId,
        total_assignments_completed: 0,
        total_assignments_late: 0,
        total_assignments_cancelled: 0,
        cumulative_rating_deficit: 0,
        rating_count: 0,
        dispute_loss_count: 0
      };
      this.workerPerformanceLedgers.set(workerId, ledger);
    }
    return ledger;
  }

  saveWorkerPerformanceLedger(ledger: WorkerPerformanceLedger): void {
    this.workerPerformanceLedgers.set(ledger.worker_id, ledger);
  }

  getWorkerCapacityLedger(workerId: string): WorkerCapacityLedger {
    let ledger = this.workerCapacityLedgers.get(workerId);
    if (!ledger) {
      ledger = {
        worker_id: workerId,
        active_assignments: 0,
        pending_reassignments: 0
      };
      this.workerCapacityLedgers.set(workerId, ledger);
    }
    return ledger;
  }

  saveWorkerCapacityLedger(ledger: WorkerCapacityLedger): void {
    this.workerCapacityLedgers.set(ledger.worker_id, ledger);
  }

  getIdempotencyKey(tenantId: string, workerId: string, assignmentId: string, endpoint: string, key: string): string {
    return `${tenantId}:${workerId}:${assignmentId}:${endpoint}:${key}`;
  }

  getIdempotencyRecord(tenantId: string, workerId: string, assignmentId: string, endpoint: string, key: string): IdempotencyRecord | undefined {
    const fullKey = this.getIdempotencyKey(tenantId, workerId, assignmentId, endpoint, key);
    return this.idempotencyRecords.get(fullKey);
  }

  saveIdempotencyRecord(record: IdempotencyRecord): void {
    const fullKey = this.getIdempotencyKey(record.tenant_id, record.worker_id, record.assignment_id, record.endpoint, record.key);
    this.idempotencyRecords.set(fullKey, record);
  }
}

export const storage = new Storage();
