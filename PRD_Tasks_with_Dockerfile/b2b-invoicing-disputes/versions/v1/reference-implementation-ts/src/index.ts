import express, { Express, Request, Response, NextFunction } from 'express';
import { initializeDatabase } from './db/schema';
import { errorHandler } from './middleware/errorHandler';

import workspacesRouter from './routes/workspaces';
import customersRouter from './routes/customers';
import contractsRouter from './routes/contracts';
import purchaseOrdersRouter from './routes/purchaseOrders';
import invoicesRouter from './routes/invoices';
import paymentsRouter from './routes/payments';
import disputesRouter from './routes/disputes';
import creditMemosRouter from './routes/creditMemos';

const app: Express = express();
const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '127.0.0.1';

app.use(express.json());

app.get('/health', (req: Request, res: Response) => {
  res.json({ status: 'ok' });
});

app.use('/workspaces', workspacesRouter);
app.use('/workspaces/:workspace_id/customers', customersRouter);
app.use('/workspaces/:workspace_id/customers/:customer_id/contracts', contractsRouter);
app.use('/workspaces/:workspace_id/contracts', contractsRouter);
app.use('/workspaces/:workspace_id/customers/:customer_id/purchase_orders', purchaseOrdersRouter);
app.use('/workspaces/:workspace_id/purchase_orders', purchaseOrdersRouter);
app.use('/workspaces/:workspace_id/customers/:customer_id/invoices', invoicesRouter);
app.use('/workspaces/:workspace_id/invoices', invoicesRouter);
app.use('/workspaces/:workspace_id/customers/:customer_id/payments', paymentsRouter);
app.use('/workspaces/:workspace_id/payments', paymentsRouter);
app.use('/workspaces/:workspace_id/invoices/:invoice_id/disputes', disputesRouter);
app.use('/workspaces/:workspace_id/disputes', disputesRouter);
app.use('/workspaces/:workspace_id/customers/:customer_id/credit_memos', creditMemosRouter);
app.use('/workspaces/:workspace_id/credit_memos', creditMemosRouter);

app.use(errorHandler);

initializeDatabase();

if (process.env.SKIP_SERVER_LIFECYCLE !== 'true') {
  app.listen(Number(PORT), HOST, () => {
    console.log(`Ledgerline B2B Invoicing API running on http://${HOST}:${PORT}`);
  });
}

export default app;
