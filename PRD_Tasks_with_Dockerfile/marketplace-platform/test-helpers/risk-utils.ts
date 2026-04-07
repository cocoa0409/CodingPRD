import { calculateMinimumReservation } from './calculations';
import {
  createOrder,
  bringAssignmentToCompleted,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer
} from './resources';

export type CompletedAssignmentRef = {
  orderId: string;
  assignmentId: string;
};

export async function prepareCompletedAssignments(
  tenantId: string,
  listingId: string,
  workerId: string,
  count: number
): Promise<CompletedAssignmentRef[]> {
  const assignments: CompletedAssignmentRef[] = [];

  for (let i = 0; i < count; i++) {
    const order = await createOrder(tenantId, listingId);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
    assignments.push({ orderId: order.id, assignmentId: assignment.id });
  }

  return assignments;
}

export async function resolveDisputesForAssignments(
  tenantId: string,
  entries: CompletedAssignmentRef[],
  reason = 'Quality issue'
): Promise<void> {
  for (const { orderId, assignmentId } of entries) {
    const dispute = await createDispute(tenantId, orderId, {
      assignment_id: assignmentId,
      raised_by: 'CUSTOMER',
      reason
    });

    await startDisputeReview(tenantId, orderId, dispute.id);
    await resolveDisputeForCustomer(tenantId, orderId, dispute.id, 3000, 500);
  }
}
