type WorkspaceId = string;
type CustomerId = string;

let workspacesToCustomers: Map<WorkspaceId, Set<CustomerId>> = new Map();
let skipConservationForCurrentTest = false;

export function resetLedgerScope(): void {
  workspacesToCustomers = new Map();
  skipConservationForCurrentTest = false;
}

export function trackWorkspace(workspaceId: string): void {
  if (!workspaceId) return;
  if (!workspacesToCustomers.has(workspaceId)) {
    workspacesToCustomers.set(workspaceId, new Set());
  }
}

export function trackCustomer(workspaceId: string, customerId: string): void {
  if (!workspaceId || !customerId) return;
  trackWorkspace(workspaceId);
  workspacesToCustomers.get(workspaceId)!.add(customerId);
}

export function snapshotLedgerScope(): Array<{ workspaceId: string; customerIds: string[] }> {
  const out: Array<{ workspaceId: string; customerIds: string[] }> = [];
  for (const [workspaceId, customerIds] of workspacesToCustomers.entries()) {
    out.push({ workspaceId, customerIds: Array.from(customerIds) });
  }
  return out;
}

export function skipConservationLawsForThisTest(): void {
  skipConservationForCurrentTest = true;
}

export function consumeSkipConservationFlag(): boolean {
  const v = skipConservationForCurrentTest;
  skipConservationForCurrentTest = false;
  return v;
}
